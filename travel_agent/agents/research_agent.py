"""Research Orchestrator Agent and its Workers.

Stage-2: Research is no longer "find attractions" -- it's **Experience
Research**, driven by `TravelRequirement.experience_preferences` /
`interests` (and, for complex destinations, by each region's
`typical_experience_types`). A user who likes music gets Tower-Records/vinyl-
shop/jazz-bar/live-house searches, not a default trip to the tower landmard.

Also owns (folded in from the old, non-reasoning `RecommendationAgent`, so the
`agents/` directory stays at exactly 4 files): candidate grouping/formatting
for presentation, and auto-selection. And the **Research Feedback Loop**: the
Orchestrator itself understands free-text feedback ("这些太游客了，多找一些
小众建筑") and turns it into a scoped, incremental re-search -- never a blind
full re-run of visa/weather/flight workers.

`visa` and `flights` remain out of scope for this round (no API/key
available) and stay as clearly-labelled estimates.
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import math
import re
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from travel_agent.agents.query_generation import QueryGenerator
from travel_agent.config.llm import get_llm
from travel_agent.destination_intelligence.service import DestinationIntelligenceService
from travel_agent.memory.schemas import MemoryContext
from travel_agent.prompts_loader import load_prompt
from travel_agent.schemas.common import Source
from travel_agent.schemas.destination import RegionCandidate
from travel_agent.schemas.experience import EXPERIENCE_TYPES, TYPE_LABEL_CN, TravelExperience
from travel_agent.schemas.research_result import (
    DestinationInfo,
    FlightOption,
    HotelOption,
    ResearchResult,
    TransportOption,
    VisaInfo,
    WeatherDay,
    WeatherInfo,
)
from travel_agent.schemas.travel_requirement import TravelRequirement
from travel_agent.tool_runtime import get_tool_manager
from travel_agent.tools.amap_places import get_place_details, search_places
from travel_agent.tools.amap_routes import calculate_route
from travel_agent.tools.search import search_travel_guides
from travel_agent.tools.visa import search_visa_information
from travel_agent.tools.weather import get_weather
from travel_agent.tools.xhs_search import XiaohongshuSearcher
from travel_agent.utils.logging import get_logger

_logger = get_logger("travel_agent.agents.research")

# Google Places `types` -> a free-text sub-category label (kept only for the
# human-readable `TravelExperience.category`; the *primary* taxonomy axis is
# now `type`, driven by the search-plan tag below, not by Google's types).
_CATEGORY_LABEL_RULES = [
    ({"shopping_mall", "market", "department_store", "clothing_store", "shoe_store",
      "jewelry_store", "shopping_area", "supermarket", "furniture_store"}, "商业购物"),
    ({"park", "natural_feature", "beach", "hiking_area", "national_park", "zoo",
      "aquarium", "garden", "botanical_garden", "hot_spring"}, "自然"),
    ({"shinto_shrine", "buddhist_temple", "hindu_temple", "church", "mosque",
      "synagogue", "place_of_worship", "historical_landmark", "history_museum",
      "museum", "monument", "cultural_landmark"}, "人文历史"),
    ({"tourist_attraction", "point_of_interest", "landmark", "observation_deck",
      "amusement_park", "stadium", "art_gallery"}, "地标"),
    ({"bar", "night_club"}, "夜生活"),
    ({"restaurant", "cafe", "bakery"}, "餐饮"),
]
_DEFAULT_CATEGORY_LABEL = "小众体验"

# Stage-2 tag-driven experience search plan: `TravelExperience.type` -> list of
# (query_template, google_place_type|None). Deliberately query-text-specific
# per tag (unlike the old broad "{dest} 景点" query) because we're now
# searching for something narrow on purpose.
_TAG_QUERY_MAP: Dict[str, List[Tuple[str, Optional[str]]]] = {
    "landmark": [("{dest} 地标景点", "tourist_attraction")],
    "culture": [("{dest} 博物馆 历史文化", "museum"), ("{dest} 展览 艺术画廊", None), ("{dest} 演出 剧场", None)],
    "nature": [("{dest} 公园 自然风光", "park")],
    "beach": [("{dest} 海滩", None)],
    "surf": [("{dest} surf spot 冲浪点", None)],
    "music": [("{dest} 黑胶唱片店", None), ("{dest} livehouse 音乐现场", None), ("{dest} 爵士酒吧", "bar")],
    "shopping": [("{dest} 潮牌店 买手店", "clothing_store"), ("{dest} 购物街区", "shopping_mall")],
    "food": [("{dest} 餐厅美食", "restaurant"), ("{dest} 特色咖啡馆", "cafe")],
    "nightlife": [("{dest} 酒吧 夜生活", "night_club")],
    "architecture": [("{dest} 历史建筑 建筑摄影", "tourist_attraction")],
    "photography": [("{dest} 风景名胜 摄影打卡", "tourist_attraction")],
    "local_life": [("{dest} 本地生活 街区漫步", None), ("{dest} 市集 社区活动", None)],
    "workshop": [("{dest} 手作工作坊 体验课程", None)],
    "wellness": [("{dest} 瑜伽课程 疗愈", None), ("{dest} 冥想 spa", None)],
}
# Requirement Agent's `experience_preferences` can carry a couple of tags one
# level finer than the canonical `EXPERIENCE_TYPES` taxonomy (see
# `agents/requirement_agent.py::_EXPERIENCE_KEYWORD_MAP`); map those onto the
# nearest canonical type for search-plan/selection purposes.
_TAG_TO_TYPE: Dict[str, str] = {"fashion": "shopping", "street_culture": "local_life"}
_INTEREST_TO_TYPE = {"购物": "shopping", "美食": "food", "人文": "culture", "自然": "nature", "摄影": "photography"}
_BASELINE_TAGS = ["landmark", "culture", "nature", "shopping", "food"]

# Round-5: dynamic query generation for `run_expansion()` -- see
# travel_agent/agents/query_generation.py. Stateless (no LLM client, no
# per-request state), so a single module-level instance is safe to share.
_query_generator = QueryGenerator()

# Cap on how many experiences get LLM-polished Activity Card prose per
# `enrich_activity_cards` call -- see that method's docstring for why.
# Live-tested: 20 items still took ~33s/3.5k output tokens for one call,
# the single largest remaining cost in a full research pass (bigger than
# the now-tag-parallelized Places search). 12 keeps every *selected* activity
# (daily_count*days is rarely more than ~12 for a typical trip) covered while
# keeping this call's latency from dominating the ~30s research budget.
_MAX_LLM_CARD_ENRICHMENT = 12


def _compact_region_hint(region: Optional[str]) -> Optional[str]:
    """Turn a verbose UI region label into a POI-friendly locality hint."""
    if not region:
        return None
    return re.split(r"[·・|｜]", region, maxsplit=1)[0].strip() or region

_TYPE_DURATION_MIN = {
    "landmark": 60, "culture": 90, "nature": 100, "beach": 120, "surf": 150,
    "shopping": 120, "food": 75, "music": 90, "nightlife": 120, "architecture": 60,
    "photography": 45, "local_life": 90, "workshop": 120, "wellness": 75,
}
_TYPE_BEST_TIME = {"nightlife": "晚上", "music": "晚上", "surf": "上午", "beach": "下午", "workshop": "上午"}

_TYPE_LABEL_CN = TYPE_LABEL_CN

_RESTAURANT_PRICE_BUCKETS_CNY = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 60,
    "PRICE_LEVEL_MODERATE": 150,
    "PRICE_LEVEL_EXPENSIVE": 350,
    "PRICE_LEVEL_VERY_EXPENSIVE": 700,
}
_HOTEL_PRICE_BUCKETS_CNY = {
    "PRICE_LEVEL_FREE": 200,
    "PRICE_LEVEL_INEXPENSIVE": 350,
    "PRICE_LEVEL_MODERATE": 650,
    "PRICE_LEVEL_EXPENSIVE": 1100,
    "PRICE_LEVEL_VERY_EXPENSIVE": 1800,
}

# Research Feedback Loop: heuristic (offline) intent parsing.
_FEEDBACK_NICHE_KEYWORDS = ["小众", "冷门", "本地人才知道", "local", "私藏"]
_FEEDBACK_EXCLUDE_MAINSTREAM_KEYWORDS = ["太游客", "太商业", "太网红", "人太多", "太多游客", "太主流", "打卡地"]
_FEEDBACK_CATEGORY_HINTS: Dict[str, str] = {
    "建筑": "architecture", "音乐": "music", "黑胶": "music", "livehouse": "music",
    "冲浪": "surf", "海滩": "beach", "夜生活": "nightlife", "酒吧": "nightlife",
    "购物": "shopping", "潮牌": "shopping", "美食": "food", "餐厅": "food",
    "摄影": "photography", "出片": "photography", "文化": "culture", "博物馆": "culture",
    "自然": "nature", "公园": "nature", "地标": "landmark", "本地": "local_life",
    "手作": "workshop", "工作坊": "workshop",
}


class _FeedbackIntent(BaseModel):
    """Internal-only structured-output target for `parse_feedback_intent`."""

    category: Optional[str] = Field(default=None, description="TravelExperience.type，若无法判断则为空")
    popularity: str = Field(default="mainstream", description="'mainstream' 或 'niche'")
    exclude: List[str] = Field(default_factory=list, description="用户明确要排除的名称")


def _infer_category_label(types: List[str]) -> str:
    type_set = set(types or [])
    for keys, label in _CATEGORY_LABEL_RULES:
        if type_set & keys:
            return label
    return _DEFAULT_CATEGORY_LABEL


def _popularity_from_review_count(count: int) -> float:
    """Heuristic 0-100 popularity score when a provider exposes review count."""
    return round(min(100.0, math.log10(max(count, 0) + 1) * 20), 1)


def _price_bucket(price_level: Optional[str], buckets: dict, default: float) -> float:
    if not price_level:
        return default
    return float(buckets.get(price_level, default))


def _extract_country(address: Optional[str], fallback: str) -> str:
    """Best-effort country extraction from a formatted address string."""
    if not address:
        return fallback
    m = re.search(r"[^\d]+$", address)
    country = m.group(0).strip(" ,") if m else ""
    return country or fallback


def _place_source(item: dict, label: str) -> Source:
    loc = item.get("location") or {}
    marker = ""
    if loc.get("lng") is not None and loc.get("lat") is not None:
        marker = f"https://uri.amap.com/marker?position={loc['lng']},{loc['lat']}&name={item.get('name', '')}&callnative=0"
    return Source(
        title=f"{item.get('name', '')} ({label})",
        url=item.get("map_uri") or marker or (f"https://www.openstreetmap.org/search?query={item.get('name', '')}" if item.get("source") == "openstreetmap" else "https://www.amap.com/"),
        source_type="openstreetmap" if item.get("source") == "openstreetmap" else "amap",
    )


def _resolve_dates(req: TravelRequirement) -> tuple[str, str]:
    if req.start_date and len(req.start_date) == 10:
        start = req.start_date
    else:
        base = req.start_date or datetime.now().strftime("%Y-%m")
        try:
            start = f"{base}-10"
            datetime.fromisoformat(start)
        except ValueError:
            start = (datetime.now() + timedelta(days=30)).date().isoformat()
    try:
        start_dt = datetime.fromisoformat(start)
    except ValueError:
        start_dt = datetime.now() + timedelta(days=30)
        start = start_dt.date().isoformat()
    duration = req.duration_days or 5
    end_dt = start_dt + timedelta(days=max(duration - 1, 0))
    return start, end_dt.date().isoformat()


class ResearchOrchestratorAgent:
    """Decides which experiences to search for, runs workers, assembles results."""

    def __init__(self) -> None:
        # tier="fast" for everything: both the structured-output call
        # (`_parse_feedback_with_llm`, needs tool-calling, which
        # deepseek-reasoner can't do) and the free-form prose calls
        # (destination summary, activity-card text) -- live-tested,
        # deepseek-reasoner "thinks" at disproportionate length even for
        # short constrained-output rewriting, which fights the latency
        # target for no quality benefit (see `config/llm.py` docstring).
        self._llm = get_llm(role="research", tier="fast")
        self._system_prompt = load_prompt("research_orchestrator_agent")
        self._xhs = XiaohongshuSearcher()
        self._destination_intelligence = DestinationIntelligenceService()

    # -- Search-plan construction (Experience Research, not fixed "attractions") --
    def _tags_for_region(self, req: TravelRequirement, region: Optional[str]) -> Optional[List[str]]:
        if not region:
            return None
        for candidate in req.region_candidates or []:
            if candidate.get("name") == region:
                types = [t for t in (candidate.get("typical_experience_types") or []) if t in EXPERIENCE_TYPES]
                if "food" not in types:
                    types.append("food")
                return types or None
        return None

    def _build_search_plan(self, req: TravelRequirement, region: Optional[str] = None) -> List[Tuple[str, str, Optional[str]]]:
        region_tags = self._tags_for_region(req, region)
        if region_tags:
            tags = list(region_tags)
        else:
            tags = list(_BASELINE_TAGS)
            for pref in req.experience_preferences or []:
                canonical = _TAG_TO_TYPE.get(pref, pref)
                if canonical in EXPERIENCE_TYPES and canonical not in tags:
                    tags.append(canonical)
            for interest in req.interests or []:
                canonical = _INTEREST_TO_TYPE.get(interest)
                if canonical and canonical not in tags:
                    tags.append(canonical)

        region_hint = _compact_region_hint(region)
        dest_label = f"{req.destination} {region_hint}".strip() if region_hint else (req.destination or "")
        plan: List[Tuple[str, str, Optional[str]]] = []
        for tag in tags:
            # The initial pass needs breadth across categories, not several
            # near-duplicate queries inside every category.  One strong query
            # per tag keeps ordinary AMap keys below their QPS ceiling; users
            # can still ask for a focused expansion later.
            query_template, place_type = _TAG_QUERY_MAP.get(tag, [("{dest} " + tag, None)])[0]
            plan.append((tag, query_template.format(dest=dest_label), place_type))
        return plan

    # -- Workers ----------------------------------------------------
    def _experience_worker(
        self,
        req: TravelRequirement,
        tag: str,
        query: str,
        place_type: Optional[str],
        exclude: Optional[List[str]] = None,
        limit: int = 6,
        region: Optional[str] = None,
    ) -> List[TravelExperience]:
        exclude_set = set(exclude or [])
        raw = get_tool_manager().call(
            search_places,
            {
                "query": query,
                "location": req.destination,
                "place_type": place_type,
                "limit": limit + len(exclude_set),
            },
            tool_name="amap_places.search_places",
        )
        if raw and raw[0].get("success") is False:
            _logger.warning("experience worker (%s) failed: %s", tag, raw[0].get("error"))
            return []

        results: List[TravelExperience] = []
        for item in raw:
            if item["name"] in exclude_set or len(results) >= limit:
                continue
            # Bulk discovery intentionally uses the search response only.
            # Fetching details for every one of 50+ candidates both adds no
            # useful review text (AMap does not expose Google-style reviews)
            # and exhausts the ordinary key's QPS before later regions run.
            opening_hours = None
            advantages: List[str] = []
            cost = _price_bucket(item.get("price_level"), _RESTAURANT_PRICE_BUCKETS_CNY, 0.0) if tag == "food" else 0.0
            coordinates = item.get("location") or {}
            results.append(
                TravelExperience(
                    name=item["name"],
                    type=tag,
                    category=_infer_category_label(item.get("types", [])),
                    location=item.get("address") or req.destination or "",
                    address=item.get("address"),
                    place_id=item.get("place_id"),
                    latitude=coordinates.get("lat"),
                    longitude=coordinates.get("lng"),
                    region=region,
                    rating=item.get("rating", 0.0),
                    popularity=_popularity_from_review_count(item.get("user_rating_count", 0)),
                    duration_minutes=_TYPE_DURATION_MIN.get(tag, 90),
                    cost=cost,
                    best_time=_TYPE_BEST_TIME.get(tag),
                    opening_hours=opening_hours,
                    advantages=advantages,
                    disadvantages=[],
                    source=_place_source(item, tag),
                )
            )
        return results

    def _run_plan(
        self, req: TravelRequirement, plan: List[Tuple[str, str, Optional[str]]], exclude: List[str],
        limit_per_query: int = 6, region: Optional[str] = None,
    ) -> List[TravelExperience]:
        """Run every (tag, query, place_type) in `plan` concurrently.

        Each tag/query group does its own Google Places search + several
        sequential place-detail lookups (real network round trips, live-tested
        at ~1s each) -- with a typical baseline+preference plan spanning
        8-10 such groups, running them one after another was the single
        biggest remaining latency cost in a research pass (far more than any
        LLM call). `exclude` is the *pre-existing* selection (already-chosen
        names from a previous turn, e.g. the feedback/expansion loops) and is
        shared unchanged across groups -- it does NOT accumulate names found
        by sibling groups *this* call the way the old sequential loop did,
        since groups now run in parallel and can't see each other's results
        as they go. The name-based dedup below (keep first occurrence) makes
        up for that: cross-category name collisions in one plan are rare
        (the same place turning up under both "landmark" and "shopping"
        searches, say) and cheap to reconcile after the fact.
        """
        if not plan:
            return []
        with cf.ThreadPoolExecutor(max_workers=len(plan)) as executor:
            futures = [
                executor.submit(
                    self._experience_worker, req, tag, query, place_type,
                    exclude=exclude, limit=limit_per_query if tag != "food" else limit_per_query + 2, region=region,
                )
                for tag, query, place_type in plan
            ]
            results = [future.result() for future in futures]

        found: List[TravelExperience] = []
        seen_names: set = set()
        for experiences in results:
            for e in experiences:
                if e.name in seen_names:
                    continue
                seen_names.add(e.name)
                found.append(e)
        return found

    def _visa_worker(self, req: TravelRequirement) -> VisaInfo:
        data = get_tool_manager().call(
            search_visa_information,
            {"passport_country": req.passport_country or "中国", "destination": req.destination},
            tool_name="visa.search_visa_information",
        )
        return VisaInfo(**data)

    def _weather_worker(self, req: TravelRequirement, start: str, end: str) -> WeatherInfo:
        try:
            start_dt = datetime.fromisoformat(start).date()
            end_dt = datetime.fromisoformat(end).date()
        except ValueError:
            start_dt = end_dt = datetime.now().date()

        days: List[WeatherDay] = []
        errors: List[str] = []
        d = start_dt
        while d <= end_dt and len(days) + len(errors) < 14:
            result = get_tool_manager().call(
                get_weather,
                {"destination": req.destination, "travel_date": d.isoformat()},
                tool_name="weather.get_weather",
            )
            if result.get("success", True):
                days.append(
                    WeatherDay(
                        date=result["date"], weather=result["weather"], temperature=result["temperature"],
                        rain_probability=result["rain_probability"], recommendation=result["recommendation"],
                    )
                )
            else:
                errors.append(result.get("error", "未知错误"))
            d += timedelta(days=1)

        if days:
            preview = "；".join(f"{w.date} {w.weather} {w.temperature}" for w in days[:3])
            summary = f"{req.destination} 天气预报：{preview}" + ("等" if len(days) > 3 else "")
        else:
            reason = errors[0] if errors else "未知原因"
            summary = f"暂无法获取「{req.destination}」的实时天气预报（{reason}），建议出发前临近日期再查询。"

        return WeatherInfo(destination=req.destination, forecast=days, summary=summary)

    def _hotel_worker(self, req: TravelRequirement) -> List[HotelOption]:
        raw = get_tool_manager().call(
            search_places,
            {"query": f"{req.destination} 酒店", "place_type": "lodging", "limit": 3},
            tool_name="amap_places.search_places",
        )
        if raw and raw[0].get("success") is False:
            _logger.warning("Hotel worker failed: %s", raw[0].get("error"))
            return []
        hotels = []
        for item in raw:
            hotels.append(
                HotelOption(
                    name=item["name"],
                    area=item.get("address") or req.destination,
                    # Google user rating is neither a hotel star class nor a
                    # dated room quote; keep both unknown without supplier evidence.
                    star_rating=None,
                    price_per_night=None,
                    price_source=None,
                    rating=item.get("rating", 0.0),
                    highlights=[],
                )
            )
        return hotels

    def _transport_worker(self, req: TravelRequirement) -> List[TransportOption]:
        origin, destination = f"{req.destination}机场", f"{req.destination}市中心"
        route = get_tool_manager().call(
            calculate_route,
            {"origin": origin, "destination": destination, "mode": "transit"},
            tool_name="amap_routes.calculate_route",
        )
        if not route.get("success", True):
            route = get_tool_manager().call(
                calculate_route,
                {"origin": origin, "destination": destination, "mode": "drive"},
                tool_name="amap_routes.calculate_route",
            )
        if not route.get("success", True):
            _logger.warning("Transport worker failed: %s", route.get("error"))
            return []
        return [
            TransportOption(
                origin=route["origin"], destination=route["destination"], mode=route["mode"],
                duration_minutes=int(round(route["duration_minutes"])), cost=route.get("cost") or 0.0,
                currency=route.get("currency", "CNY"),
            )
        ]

    def _web_research_worker(self, req: TravelRequirement) -> tuple[List[Source], Optional[str]]:
        keywords = list(req.interests or []) + list(req.experience_preferences or [])
        results = get_tool_manager().call(
            search_travel_guides,
            {"destination": req.destination, "keywords": keywords, "platform": "web", "limit": 3},
            tool_name="search.search_travel_guides",
        )
        if results and results[0].get("success") is False:
            _logger.info("Web guide search unavailable: %s", results[0].get("error"))
            return [], f"网页攻略搜索不可用：{results[0].get('error')}"
        return ([Source(title=r["title"], url=r["url"] or "",
                        source_type="web", snippet=r.get("snippet")) for r in results], None)

    def _social_research_worker(self, req: TravelRequirement) -> tuple[List[Source], Optional[str]]:
        """Real 小红书 search via `opencli` + the user's logged-in Chrome
        (`XiaohongshuSearcher`, `tools/xhs_search.py`) -- replaces the old
        Agent Reach `search_travel_guides(platform="xiaohongshu")` path, which
        always failed (no `xhs` CLI installed). Issues a single combined query
        (destination + top interest/experience tag) to stay inside the
        research time budget; `run_feedback` uses the fuller query set when a
        user explicitly asks for more/different content."""
        interests = list(req.experience_preferences or []) + list(req.interests or [])
        query = self._xhs.build_interest_queries(req.destination or "", interests)[0]
        results = get_tool_manager().call(
            self._xhs.search,
            {"keyword": query, "limit": 5},
            tool_name="xhs_search.search",
        )
        if results and results[0].get("success") is False:
            _logger.info("Xiaohongshu search unavailable: %s", results[0].get("error"))
            return [], f"小红书实时搜索不可用：{results[0].get('error')}"
        return ([
            Source(
                title=r["title"] + (f"（{r['author']}，{r['likes']} 赞）" if r.get("author") else ""),
                url=r["url"] or "",
                source_type="xiaohongshu",
                snippet=r.get("content"),
            )
            for r in results
        ], None)

    def _flight_worker(self, req: TravelRequirement) -> List[FlightOption]:
        base_price = 2200.0
        return [
            FlightOption(airline="(预估-暂无航班API)", flight_number="N/A", departure_city=req.departure_city or "出发地",
                         arrival_city=req.destination, departure_time="09:00", arrival_time="13:30", price=base_price),
            FlightOption(airline="(预估-暂无航班API)", flight_number="N/A", departure_city=req.destination,
                         arrival_city=req.departure_city or "出发地", departure_time="20:00", arrival_time="23:30",
                         price=base_price * 0.9),
        ]

    def _destination_info(
        self, req: TravelRequirement, experiences: List[TravelExperience], weather: WeatherInfo, guides: List[Source]
    ) -> DestinationInfo:
        sample_address = experiences[0].location if experiences else None
        country = _extract_country(sample_address, req.destination)

        summary = None
        if self._llm is not None:
            try:
                context = (
                    f"目的地: {req.destination}\n"
                    f"检索到的体验: {', '.join(e.name for e in experiences[:6]) or '暂无数据'}\n"
                    f"天气: {weather.summary}\n"
                    f"攻略来源标题: {', '.join(g.title for g in guides[:3]) or '暂无'}\n"
                )
                messages = []
                if self._system_prompt:
                    messages.append(("system", self._system_prompt))
                messages.append(("human", f"请仅根据以下真实检索到的信息，为「{req.destination}」写一段 2-3 句的中文目的地简介，不要编造未提供的信息：\n{context}"))
                resp = self._llm.invoke(messages)
                summary = (resp.content or "").strip() or None
            except Exception as exc:  # noqa: BLE001 - fall back to a plain summary
                _logger.warning("destination_info LLM summary failed: %s", exc)

        if not summary:
            summary = f"{req.destination}：已检索到 {len(experiences)} 个体验候选，详情见下方研究结果。"

        return DestinationInfo(name=req.destination, country=country, summary=summary)

    # -- Stage-3: Activity Card enrichment -----------------------------
    def _heuristic_card_fields(self, e: TravelExperience, req: TravelRequirement) -> None:
        """Always-on, LLM-free baseline so every candidate is a full card
        even fully offline -- `_enrich_cards_with_llm` only refines on top."""
        label = _TYPE_LABEL_CN.get(e.type, e.category or e.type)
        if not e.short_description:
            region_prefix = f"{e.region}的" if e.region else ""
            e.short_description = f"{region_prefix}{label}体验：{e.name}。"
        if not e.detailed_description:
            parts = [f"{e.name}位于{e.location}，属于{label}类体验。"]
            if e.rating:
                parts.append(f"高德评分 {e.rating:.1f}。")
            if e.opening_hours:
                parts.append(f"营业时间：{e.opening_hours}。")
            e.detailed_description = "".join(parts)
        if not e.why_recommended:
            wanted_types = set(req.experience_preferences or [])
            wanted_types.update(_INTEREST_TO_TYPE[i] for i in (req.interests or []) if i in _INTEREST_TO_TYPE)
            reasons = []
            if e.type in wanted_types:
                reasons.append(f"符合您偏好的{label}类体验")
            if e.popularity_level == "niche":
                reasons.append("更偏小众/本地化，不那么游客向")
            if not reasons:
                reasons.append(f"作为{label}类的代表性选择")
            e.why_recommended = reasons
        if not e.highlights:
            e.highlights = list(e.advantages[:2]) or [f"{label}，评分 {e.rating:.1f}" if e.rating else label]
        if not e.drawbacks:
            e.drawbacks = ["实际体验可能因季节/时段有所差异，建议出发前再次确认。"]
        if not e.subcategories:
            e.subcategories = [label]
        if not e.target_travelers:
            e.target_travelers = ["独自旅行", "情侣", "小团体"]
        if not e.suitable_for_preferences:
            e.suitable_for_preferences = [e.type]
        if e.reservation_required is None:
            e.reservation_required = e.type in ("wellness", "workshop", "food")
        e.confidence = 0.6 if e.source.source_type != "mock" else 0.4

    def _enrich_cards_with_llm(self, experiences: List[TravelExperience]) -> None:
        """Batch-rewrite the heuristic card text into more natural prose,
        strictly grounded in each item's own real fields -- never invents a
        new fact, price or opening time (same discipline as
        `PlannerAgent._refine_reasons_with_llm`). Leaves the heuristic
        baseline untouched on any failure."""
        payload = [
            {
                "index": i,
                "name": e.name,
                "type": e.type,
                "region": e.region,
                "rating": e.rating,
                "opening_hours": e.opening_hours,
                "advantages": e.advantages[:3],
            }
            for i, e in enumerate(experiences)
        ]
        messages = []
        if self._system_prompt:
            messages.append(("system", self._system_prompt))
        messages.append((
            "human",
            "请仅根据下面每一项已知的真实字段，为每个活动撰写更自然的中文 Activity Card 文案："
            "short_description(一句话，不超过30字)、detailed_description(2-3句)、"
            "why_recommended(1-2条推荐理由)、highlights(1-3个亮点)、drawbacks(0-2个可能缺点)。"
            "不要编造未提供的价格、时间或设施信息。"
            '严格以 JSON 数组返回，形如 [{"index":0,"short_description":"...","detailed_description":"...",'
            '"why_recommended":["..."],"highlights":["..."],"drawbacks":["..."]}, ...]，不要输出其他文字。\n'
            f"{json.dumps(payload, ensure_ascii=False)}",
        ))
        try:
            resp = self._llm.invoke(messages)
            content = (resp.content or "").strip()
            if content.startswith("```"):
                content = content.strip("`")
                content = content.split("\n", 1)[-1] if "\n" in content else content
            refined = json.loads(content)
            by_index = {r["index"]: r for r in refined if "index" in r}
            for i, e in enumerate(experiences):
                r = by_index.get(i)
                if not r:
                    continue
                if r.get("short_description"):
                    e.short_description = r["short_description"]
                if r.get("detailed_description"):
                    e.detailed_description = r["detailed_description"]
                if r.get("why_recommended"):
                    e.why_recommended = r["why_recommended"]
                if r.get("highlights"):
                    e.highlights = r["highlights"]
                if r.get("drawbacks"):
                    e.drawbacks = r["drawbacks"]
                e.confidence = max(e.confidence, 0.8)
        except Exception as exc:  # noqa: BLE001 - keep heuristic cards on any failure
            _logger.warning("LLM activity-card enrichment failed, keeping heuristic text: %s", exc)

    def enrich_activity_cards(self, experiences: List[TravelExperience], req: TravelRequirement) -> None:
        """Fill every Activity Card field (in place) -- heuristic baseline
        always runs so offline/no-LLM callers still get full cards; LLM
        refinement is best-effort on top, capped to the `_MAX_LLM_CARD_ENRICHMENT`
        highest-popularity items.

        Live-tested: a full requirement (baseline + a couple of preference
        tags) can easily surface 40-60+ experiences, and sending all of them
        through one LLM call scales the prompt/output size (and therefore
        latency) linearly with candidate count -- one such call measured
        ~90s/8k output tokens, which alone blows the research time budget
        regardless of model. The heuristic baseline (above) already gives
        every card full text, so capping which ones additionally get
        LLM-polished prose is a pure latency/quality tradeoff, not a
        completeness one.
        """
        for e in experiences:
            self._heuristic_card_fields(e, req)
        if self._llm is None or not experiences:
            return
        to_enrich = sorted(experiences, key=lambda e: e.popularity, reverse=True)[:_MAX_LLM_CARD_ENRICHMENT]
        self._enrich_cards_with_llm(to_enrich)

    # -- Stage-3: candidate coverage / targeted-research closed loop --------
    def check_coverage(self, req: TravelRequirement, research: ResearchResult) -> Dict[str, Any]:
        """Design doc section XVI: compute whether the candidate pool is rich
        enough (volume + category coverage) before Planning even starts,
        instead of only discovering thinness after the fact."""
        days = req.duration_days or 5
        daily_count = req.daily_attraction_count or 3
        required_non_food = max(daily_count * days, 3)
        required_food = max(days + 1, 2)
        required_total = required_non_food + required_food

        non_food = [e for e in research.experiences if e.type != "food"]

        wanted_types = list(dict.fromkeys(
            list(req.experience_preferences or [])
            + [_INTEREST_TO_TYPE[i] for i in (req.interests or []) if i in _INTEREST_TO_TYPE]
        ))
        category_coverage = {t: len([e for e in non_food if e.type == t]) for t in wanted_types}
        minimum_per_category = max(2, daily_count)
        underrepresented = [t for t in wanted_types if category_coverage.get(t, 0) < minimum_per_category]

        return {
            "required_activity_count": required_total,
            "available_activity_count": len(research.experiences),
            "category_coverage": category_coverage,
            "underrepresented_categories": underrepresented,
            "needs_more_research": len(research.experiences) < required_total or bool(underrepresented),
        }

    def trigger_targeted_research(
        self,
        req: TravelRequirement,
        research: ResearchResult,
        coverage: Optional[Dict[str, Any]] = None,
        region: Optional[str] = None,
    ) -> ResearchResult:
        coverage = coverage or self.check_coverage(req, research)
        if not coverage.get("needs_more_research"):
            return research
        missing = list(coverage.get("underrepresented_categories") or [])
        if not missing:
            present = {e.type for e in research.experiences}
            missing = [t for t in _BASELINE_TAGS if t not in present] or ["local_life"]
        return self.run_expansion(req, research, missing, region=region)

    # -- Orchestration ------------------------------------------------
    def _discover_specialties(
        self, req: TravelRequirement, region: Optional[str], memory_context: Optional[MemoryContext]
    ) -> Tuple[List[str], List[str]]:
        """Round-6: before falling back to the generic baseline search plan,
        ask the `travel_guides` RAG knowledge base (+ profile, for
        personalization) what this destination/region is actually known for.

        Returns `(discovered_topics, evidence_source_titles)` -- an empty
        result (no ingested guide covers this place, or Chroma is
        unavailable) is a normal outcome, not an error: the caller just
        proceeds with whatever it already had (`RAG_NO_RESULT` -> fall
        through, per requirement doc section 34), which is why every step
        here is wrapped in one broad try/except rather than letting a RAG
        hiccup take down the whole research pass.

        Deliberately heuristic-only (`llm=None`) for the rewrite/rerank
        steps, even when `self._llm` is configured -- confirmed live: with
        a real LLM, `rewrite_query()`/`rerank()`'s inherent sampling
        variance (temperature=0.3, not 0) made this method flip between
        finding and not finding the *same* single matching chunk across
        back-to-back calls with identical inputs. This step's job is broad
        discovery of "what should we search for" -- a false positive just
        costs one extra, cheap Google Places query, but a false negative
        (the LLM subjectively rerank-rejecting the only chunk covering a
        thinly-populated knowledge base) silently reproduces the exact
        "adding data made no difference" symptom this method exists to fix.
        The LLM path is worth its cost in `context_assembler.py`, where
        precision matters because a rejected chunk is one the user would
        otherwise directly read; it isn't worth it here.
        """
        dest_label = f"{req.destination} {region}".strip() if region else (req.destination or "")
        if not dest_label:
            return [], []
        try:
            from travel_agent.memory.context_builder import flatten_profile_statements
            from travel_agent.rag.query_rewriter import rewrite_query
            from travel_agent.rag.reranker import rerank
            from travel_agent.rag.result_merger import merge_and_score
            from travel_agent.rag.retrievers.parallel_retriever import retrieve_all_sync
            from travel_agent.rag.schemas import RetrievalContext

            profile_hint = flatten_profile_statements(memory_context.profile_statements) if memory_context else {}
            query_text = f"{dest_label} 有什么特色玩法和本地体验"
            rewritten = rewrite_query(
                query_text, travel_requirement=req, user_profile=profile_hint,
                retrieval_mode="RAG_AND_WEB", llm=None,
            )
            rewritten.destination_filters = {"destination": region or req.destination or ""}

            parallel_result = retrieve_all_sync(
                RetrievalContext(rewritten=rewritten, top_k=15), sources=["dense", "keyword", "metadata"]
            )
            if not parallel_result.chunks:
                return [], []

            merged = merge_and_score(parallel_result.chunks)
            reranked = rerank(query_text, merged, rewritten_query=rewritten, llm=None)
            lookup = {c.chunk_id: c for c in merged}

            topics: List[str] = []
            titles: List[str] = []
            for item in reranked:
                if not item.selected:
                    continue
                chunk = lookup.get(item.chunk_id)
                if chunk is None:
                    continue
                for topic in (chunk.metadata.get("activity_topics") or "").split("|"):
                    if topic and topic not in topics:
                        topics.append(topic)
                title = chunk.metadata.get("source_title")
                if title and title not in titles:
                    titles.append(title)
            return topics, titles
        except Exception as exc:  # noqa: BLE001 -- RAG is an enhancement here, never blocks research
            _logger.warning("RAG specialty discovery failed for %s, falling back to baseline plan: %s", dest_label, exc)
            return [], []

    def _region_candidate_for(
        self, req: TravelRequirement, region: Optional[str], discovered_topics: List[str]
    ) -> Optional[RegionCandidate]:
        """Merge RAG-discovered topics into whatever region profile is
        already known (Destination Intelligence's static known-destination
        table, or a prior region split), or -- if there's no known profile
        at all, including for destinations that never went through region-
        split assessment -- build a fresh one on the spot from the
        discovered topics. `None` only when there's neither."""
        existing_data = next((c for c in (req.region_candidates or []) if c.get("name") == region), None) if region else None
        existing = RegionCandidate(**existing_data) if existing_data else None

        if existing is not None:
            if discovered_topics:
                existing.signature_experiences = list(dict.fromkeys(existing.signature_experiences + discovered_topics))
            return existing

        if not discovered_topics:
            return None
        return self._destination_intelligence.profile_region(
            req.destination or "", region or req.destination or "", focus_hint=discovered_topics,
            llm=self._llm, system_prompt=self._system_prompt,
        )

    def _places_worker(
        self,
        req: TravelRequirement,
        extra_exclude: Optional[List[str]] = None,
        memory_context: Optional[MemoryContext] = None,
    ) -> List[TravelExperience]:
        """Multi-region experience search, kept sequential *within* itself
        (each region's dedup depends on the previous region's picks) but run
        as a single unit alongside the other worker categories in `run_full`.

        `extra_exclude` (Round-6 Phase 5): names the user has historically
        rejected (from `MemoryContext.episodic`, see
        `memory/context_builder.py::rejected_experience_names`) -- merged
        into the same per-region dedup exclude list so a brand-new trip
        doesn't re-suggest something already turned down in a past trip.

        `memory_context` (Round-6 Phase 6.5): per region, `_discover_
        specialties()` checks the RAG knowledge base (+ profile) for what
        this place is actually known for *before* searching Google Places,
        and `_region_candidate_for()` folds any discovered topics into a
        `RegionCandidate` so `QueryGenerator` can turn them into real
        queries -- same generator `run_expansion()` already uses, just now
        also driving the *first* search pass instead of only the automatic
        feasibility-expansion one. If nothing is discovered (new knowledge
        base, or this place genuinely isn't covered yet), this reduces to
        exactly the old baseline-tag behavior -- `RAG_NO_RESULT` is a normal
        outcome, not a degraded one."""
        experiences: List[TravelExperience] = []
        regions = req.region_preferences if (req.region_split_confirmed and req.region_preferences) else [None]
        base_exclude = list(extra_exclude or [])
        for region in regions:
            topics, _evidence_titles = self._discover_specialties(req, region, memory_context)
            region_candidate = self._region_candidate_for(req, region, topics)

            plan = self._build_search_plan(req, region=region)
            existing_tags = {tag for tag, _query, _place_type in plan}
            region_hint = _compact_region_hint(region)
            dest_label = f"{req.destination} {region_hint}".strip() if region_hint else (req.destination or "")
            rag_plan = _query_generator.generate(
                focus=[t for t in topics if t not in existing_tags],
                dest_label=dest_label, region_candidate=region_candidate, tag_query_map=_TAG_QUERY_MAP,
            )
            plan = plan + [(tag, query, place_type) for query, place_type, tag in rag_plan]
            deduped_plan: List[Tuple[str, str, Optional[str]]] = []
            seen_queries: set = set()
            for entry in plan:
                query_key = entry[1].strip().lower()
                if query_key in seen_queries:
                    continue
                seen_queries.add(query_key)
                deduped_plan.append(entry)
            plan = deduped_plan[:10]

            experiences.extend(
                self._run_plan(req, plan, exclude=base_exclude + [e.name for e in experiences], region=region)
            )
        self.enrich_activity_cards(experiences, req)
        return experiences

    def run_full(
        self,
        req: TravelRequirement,
        progress_cb: Optional[Callable[[str, str], None]] = None,
        extra_exclude: Optional[List[str]] = None,
        memory_context: Optional[MemoryContext] = None,
    ) -> ResearchResult:
        """Run every worker relevant to the requirement (full research pass).

        Stage-4: the independent worker categories (Google Places, web
        guides, 小红书, visa, weather, routes, hotels) run concurrently via
        `ThreadPoolExecutor` -- same pattern the Stage-3 intent interpreter
        already uses for its Fast/Deep paths (plain function calls doing
        blocking I/O, not `asyncio`, since the whole codebase is synchronous).
        `destination_info` runs after, since it summarizes the others'
        output. `progress_cb(worker_name, status)` -- if given -- is invoked
        as each worker starts/finishes, so a concurrent poller (see
        `travel_agent/execution/research_jobs.py`) can show live progress.
        """
        start, end = _resolve_dates(req)

        def _report(name: str, status: str) -> None:
            if progress_cb:
                try:
                    progress_cb(name, status)
                except Exception:  # noqa: BLE001 - a broken progress sink must never fail research
                    pass

        workers: Dict[str, Callable[[], Any]] = {
            "amap_places": lambda: self._places_worker(req, extra_exclude=extra_exclude, memory_context=memory_context),
            "web_guides": lambda: self._web_research_worker(req),
            "xiaohongshu": lambda: self._social_research_worker(req),
            "visa": lambda: self._visa_worker(req),
            "weather": lambda: self._weather_worker(req, start, end),
            "routes": lambda: self._transport_worker(req),
            "hotels": lambda: self._hotel_worker(req),
        }

        results: Dict[str, Any] = {}
        with cf.ThreadPoolExecutor(max_workers=len(workers)) as executor:
            futures = {}
            for name, fn in workers.items():
                _report(name, "running")
                futures[executor.submit(fn)] = name
            for future in cf.as_completed(futures):
                name = futures[future]
                try:
                    results[name] = future.result()
                except Exception as exc:  # noqa: BLE001 - one worker failing must not sink the whole pass
                    _logger.warning("research worker %s failed: %s", name, exc)
                    results[name] = None
                _report(name, "done")

        experiences: List[TravelExperience] = results.get("amap_places") or []
        web_notes, web_warning = results.get("web_guides") or ([], "网页攻略搜索执行失败")
        social_notes, social_warning = results.get("xiaohongshu") or ([], "小红书实时搜索执行失败")
        visa_info: VisaInfo = results.get("visa") or VisaInfo()
        weather: WeatherInfo = results.get("weather") or WeatherInfo(
            destination=req.destination, forecast=[], summary=f"{req.destination} 天气信息获取失败。"
        )
        transportation: List[TransportOption] = results.get("routes") or []
        hotels: List[HotelOption] = results.get("hotels") or []
        flights = self._flight_worker(req)  # pure computation, no IO -- not worth a thread

        destination_info = self._destination_info(req, experiences, weather, web_notes + social_notes)

        all_sources = [e.source for e in experiences] + web_notes + social_notes
        if visa_info.notes:
            all_sources.append(Source(title="签证信息", url="https://mock-visa-data.example.com", source_type="mock"))

        return ResearchResult(
            destination_info=destination_info, visa_info=visa_info, weather=weather, flights=flights,
            hotels=hotels, experiences=experiences, transportation=transportation,
            web_notes=web_notes, social_notes=social_notes, sources=all_sources,
            warnings=[warning for warning in (web_warning, social_warning) if warning] + [
                "签证信息当前是占位数据，不能作为出入境依据。",
                "航班和价格当前是规则估算，并非实时航班 API 数据。",
            ],
        )

    # -- Research Feedback Loop ----------------------------------------
    def parse_feedback_intent(self, message: str, req: TravelRequirement) -> Dict[str, Any]:
        """Understand free-text feedback ("这些太游客了，多找一些小众建筑") and turn
        it into a scoped research intent -- never a blind full re-search."""
        if self._llm is not None:
            parsed = self._parse_feedback_with_llm(message)
            if parsed is not None:
                return parsed
        return self._parse_feedback_heuristic(message)

    def _parse_feedback_with_llm(self, message: str) -> Optional[Dict[str, Any]]:
        try:
            # method="function_calling": see requirement_agent.py's identical
            # comment -- DeepSeek rejects the response_format=json_schema
            # default for pydantic targets.
            structured_llm = self._llm.with_structured_output(_FeedbackIntent, method="function_calling")
            messages = []
            if self._system_prompt:
                messages.append(("system", self._system_prompt))
            messages.append((
                "human",
                "用户对候选体验给出了以下反馈，请判断其意图：\n"
                f"「{message}」\n"
                "category 取值应来自 landmark/nature/beach/surf/music/shopping/food/nightlife/culture/"
                "architecture/photography/local_life/workshop（判断不出就留空）；"
                "popularity 判断用户是否想要更小众/冷门的内容（niche）还是无所谓（mainstream）；"
                "exclude 列出用户明确要排除的地点名称（若提到）。",
            ))
            result = structured_llm.invoke(messages)
            if isinstance(result, _FeedbackIntent):
                return result.model_dump()
        except Exception:
            return None
        return None

    def _parse_feedback_heuristic(self, message: str) -> Dict[str, Any]:
        text = message or ""
        category = None
        for keyword, tag in _FEEDBACK_CATEGORY_HINTS.items():
            if keyword in text:
                category = tag
                break
        wants_niche = any(k in text for k in _FEEDBACK_NICHE_KEYWORDS + _FEEDBACK_EXCLUDE_MAINSTREAM_KEYWORDS)
        return {"category": category, "popularity": "niche" if wants_niche else "mainstream", "exclude": []}

    def run_feedback(
        self,
        req: TravelRequirement,
        existing: ResearchResult,
        message: str,
        progress_cb: Optional[Callable[[str, str], None]] = None,
        extra_exclude: Optional[List[str]] = None,
        preferred_topics: Optional[List[str]] = None,
    ) -> ResearchResult:
        """Incremental, feedback-scoped re-search. Never touches visa/weather/flight.

        `preferred_topics` (Round-6): explicit activity types already parsed
        out of the message by `graph/nodes.py::user_selection_node` (via
        `rag/query_rewriter.py`'s multi-topic heuristic, same `topic_vocab.py`
        table RAG retrieval uses) -- when given, searches for *all* of them
        via `QueryGenerator` (same generator `run_expansion()` already uses),
        instead of re-parsing the free text through `parse_feedback_intent()`,
        whose single-category heuristic (first keyword match wins) silently
        drops every topic after the first in a message naming several at
        once (confirmed live: "我要瑜伽，跳舞，浮潜，冲浪，spa，看日落" only ever
        searched for one of them)."""
        if progress_cb:
            try:
                progress_cb("amap_places", "running")
            except Exception:  # noqa: BLE001
                pass

        exclude_names = [e.name for e in existing.experiences] + list(extra_exclude or [])
        dest_label = req.destination or ""
        new_experiences: List[TravelExperience] = []

        if preferred_topics:
            query_plan = _query_generator.generate(focus=preferred_topics, dest_label=dest_label, tag_query_map=_TAG_QUERY_MAP)
            for query, place_type, tag in query_plan:
                found = self._experience_worker(
                    req, tag, query, place_type, exclude=exclude_names + [e.name for e in new_experiences], limit=6,
                )
                new_experiences.extend(found)
        else:
            intent = self.parse_feedback_intent(message, req)
            tag = intent.get("category") or "local_life"
            niche = intent.get("popularity") == "niche"
            exclude_names = exclude_names + list(intent.get("exclude") or [])

            for query_template, place_type in _TAG_QUERY_MAP.get(tag, [("{dest} " + tag, None)]):
                query = query_template.format(dest=dest_label)
                if niche:
                    query += " 小众 本地推荐"
                found = self._experience_worker(
                    req, tag, query, place_type, exclude=exclude_names + [e.name for e in new_experiences], limit=6,
                )
                if niche:
                    for e in found:
                        e.popularity_level = "niche"
                new_experiences.extend(found)

        self.enrich_activity_cards(new_experiences, req)
        updated = existing.model_copy(deep=True)
        updated.experiences = existing.experiences + new_experiences
        updated.sources = existing.sources + [e.source for e in new_experiences]
        if progress_cb:
            try:
                progress_cb("amap_places", "done")
            except Exception:  # noqa: BLE001
                pass
        return updated

    # -- Planner-triggered expansion (feasibility loop, no user turn) --------
    def run_expansion(
        self,
        req: TravelRequirement,
        existing: ResearchResult,
        missing_categories: List[str],
        region: Optional[str] = None,
        region_candidate: Optional[RegionCandidate] = None,
        progress_cb: Optional[Callable[[str, str], None]] = None,
        extra_exclude: Optional[List[str]] = None,
    ) -> ResearchResult:
        if progress_cb:
            try:
                progress_cb("amap_places", "running")
            except Exception:  # noqa: BLE001
                pass
        exclude_names = [e.name for e in existing.experiences] + list(extra_exclude or [])
        new_experiences: List[TravelExperience] = []
        region_hint = _compact_region_hint(region)
        dest_label = f"{req.destination} {region_hint}".strip() if region_hint else (req.destination or "")
        # `region_candidate` (Destination Intelligence, Phase 4) already
        # contributes its own signature-experience queries below regardless
        # of `focus` -- only fall back to the old blanket "local_life" probe
        # when there's neither a specific ask NOR a discovered profile to
        # search from.
        focus = list(missing_categories) if missing_categories else ([] if region_candidate else ["local_life"])
        query_plan = _query_generator.generate(
            focus=[_TAG_TO_TYPE.get(tag, tag) for tag in focus],
            dest_label=dest_label,
            region_candidate=region_candidate,
            tag_query_map=_TAG_QUERY_MAP,
        )
        for query, place_type, tag in query_plan:
            found = self._experience_worker(
                req, tag, query, place_type,
                exclude=exclude_names + [e.name for e in new_experiences], limit=6, region=region,
            )
            new_experiences.extend(found)
        self.enrich_activity_cards(new_experiences, req)

        updated = existing.model_copy(deep=True)
        updated.experiences = existing.experiences + new_experiences
        updated.sources = existing.sources + [e.source for e in new_experiences]
        if progress_cb:
            try:
                progress_cb("amap_places", "done")
            except Exception:  # noqa: BLE001
                pass
        return updated

    def auto_select_additional(self, existing_selected: List[dict], new_experiences: List[TravelExperience], target_total: int) -> List[dict]:
        """Auto-extend a selection with newly-expanded experiences (no user turn)."""
        selected = list(existing_selected)
        selected_names = {e["name"] for e in selected}
        for e in sorted(new_experiences, key=lambda x: x.popularity, reverse=True):
            if len(selected) >= target_total:
                break
            if e.name in selected_names:
                continue
            selected.append(e.model_dump())
            selected_names.add(e.name)
        return selected

    # -- Candidate presentation (folded in from the old RecommendationAgent) --
    def build_candidates(self, research: ResearchResult) -> Dict[str, Dict[str, List[dict]]]:
        """Return `{"experiences": {type: [candidate,...]}}`."""
        by_type: Dict[str, List[dict]] = {}
        for e in research.experiences:
            by_type.setdefault(e.type, []).append(e.model_dump())
        return {"experiences": by_type}

    def build_summary_message(self, candidates: Dict[str, Dict[str, List[dict]]]) -> str:
        # Every candidate gets at least its short_description alongside the
        # name -- design doc section XV explicitly forbids surfacing bare
        # names with no way for the user to judge whether it's worth picking.
        lines = ["根据搜索结果，为您整理了以下体验候选："]
        for etype, items in candidates.get("experiences", {}).items():
            label = _TYPE_LABEL_CN.get(etype, etype)
            lines.append(f"【{label}】")
            for i in items:
                desc = i.get("short_description") or ""
                lines.append(f"- {i['name']}" + (f"：{desc}" if desc else ""))
        lines.append(
            "请告诉我您想保留/删除哪些（例如“去掉XX”“我要XX、YY和ZZ”），"
            "或直接回复“帮我推荐”让我自动挑选；也可以直接说出您的反馈"
            "（例如“这些太游客了，多找一些小众建筑”），我会针对性地补充搜索。"
        )
        return "\n".join(lines)

    def auto_select(
        self,
        candidates: Dict[str, Dict[str, List[dict]]],
        daily_count: int,
        days: int,
        preferred_types: Optional[List[str]] = None,
    ) -> Dict[str, List[dict]]:
        """Pick defaults that follow the user's interests and cover regions.

        Type diversity is useful only after relevance.  The old round-robin
        selected a shop for a history-and-food trip merely because a shopping
        bucket existed.  Prefer requested and generally trip-worthy types,
        seed one representative item per chosen region, then fill remaining
        slots by quality.  Food is ranked separately for meal slots.
        """
        by_type = candidates.get("experiences", {})
        preferred = list(dict.fromkeys(_TAG_TO_TYPE.get(t, t) for t in (preferred_types or [])))
        default_order = ["landmark", "culture", "nature", "architecture", "local_life", "photography", "workshop"]
        allowed_order = list(dict.fromkeys([t for t in preferred if t != "food"] + default_order))
        # Keep newly researched/custom activities selectable (e.g. yoga,
        # snorkeling, dance) even before they have entered the requirement's
        # canonical preference list.  Only generic distractor buckets stay
        # opt-in when the user did not ask for them.
        distractors = {"shopping", "nightlife", "music"} - set(preferred)
        allowed_order.extend(
            t for t in by_type if t not in allowed_order and t != "food" and t not in distractors
        )

        def score(item: dict) -> tuple:
            name = item.get("name", "")
            representative = 1 if re.search(r"长城|故宫|博物馆|公园|遗址|天安门|天坛|颐和园", name) else 0
            return (representative, float(item.get("popularity") or 0), float(item.get("rating") or 0))

        def food_score(item: dict) -> tuple:
            name = item.get("name", "")
            cafe = 1 if re.search(r"咖啡|coffee|cafe|星巴克|m stand", name, re.I) else 0
            return (-cafe, float(item.get("popularity") or 0), float(item.get("rating") or 0))

        food_pool = sorted(by_type.get("food", []), key=food_score, reverse=True)
        non_food_pools = {
            t: sorted(list(by_type.get(t, [])), key=score, reverse=True)
            for t in allowed_order if by_type.get(t)
        }

        target_non_food = max(daily_count * days, 3)
        target_food = max(days + 1, 2)

        selected_non_food: List[dict] = []
        selected_names: set = set()

        # Cover each explicitly researched region before filling globally.
        all_non_food = [item for t, items in by_type.items() if t != "food" for item in items]
        regions = list(dict.fromkeys(item.get("region") for item in all_non_food if item.get("region")))
        for region in regions:
            region_items = [item for item in all_non_food if item.get("region") == region]
            if not region_items:
                continue
            best = max(region_items, key=score)
            if best.get("name") not in selected_names:
                selected_non_food.append(best)
                selected_names.add(best.get("name"))

        type_cycle = list(non_food_pools.keys())
        i = 0
        while len(selected_non_food) < target_non_food and type_cycle:
            if all(not pool for pool in non_food_pools.values()):
                break
            t = type_cycle[i % len(type_cycle)]
            pool = non_food_pools[t]
            while pool and pool[0].get("name") in selected_names:
                pool.pop(0)
            if pool:
                item = pool.pop(0)
                selected_non_food.append(item)
                selected_names.add(item.get("name"))
            i += 1

        return {"experiences": selected_non_food + food_pool[:target_food]}
