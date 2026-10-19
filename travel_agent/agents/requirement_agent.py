"""Requirement Agent: collects and confirms the user's travel requirement.

Responsible for turning free-form natural language into a structured
`TravelRequirement`. Uses an LLM (via `config.llm.get_llm`) with structured
output when one is configured; otherwise falls back to a deterministic
regex/keyword heuristic extractor so the whole pipeline can run fully
offline (this is what powers `demo.py` without any API key).

Each turn produces:
1. 当前旅行需求总结 (summary)
2. 已确认信息 (confirmed_fields)
3. 缺失信息 (missing_fields) -- only required fields block progression
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from travel_agent.config.llm import get_llm
from travel_agent.destination_intelligence.service import DestinationIntelligenceService
from travel_agent.prompts_loader import load_prompt
from travel_agent.schemas.destination import DestinationComplexityAssessment
from travel_agent.schemas.travel_requirement import (
    INTEREST_OPTIONS,
    PACE_OPTIONS,
    RequirementExtractionResult,
    TravelRequirement,
)

_CN_NUM = {
    "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

_INTEREST_SYNONYMS = {
    "购物": ["购物", "买买买", "血拼", "shopping"],
    "美食": ["美食", "吃", "小吃", "料理", "美食探店"],
    "人文": ["人文", "历史", "文化", "古迹", "神社", "寺庙"],
    "自然": ["自然", "风景", "公园", "海边", "山"],
    "摄影": ["摄影", "拍照", "出片"],
}

_PACE_KEYWORDS = {
    "特种兵": ["特种兵", "打卡", "尽量多", "赶行程", "高效"],
    "松弛": ["不想太累", "松弛", "慢一点", "悠闲", "轻松", "休闲"],
}

# Stage-2: richer experience-preference tags (`TravelExperience.type` taxonomy),
# distinct from the coarse `interests` categories above. "我喜欢东京的潮流文化"
# should surface fashion/music/street_culture/local_life, not just "购物".
_EXPERIENCE_KEYWORD_MAP: Dict[str, List[str]] = {
    "潮流": ["fashion", "street_culture", "local_life"],
    "潮牌": ["fashion", "shopping"],
    "街头文化": ["street_culture", "local_life"],
    "黑胶": ["music"],
    "livehouse": ["music", "nightlife"],
    "音乐": ["music"],
    "爵士": ["music"],
    "建筑": ["architecture"],
    "摄影": ["photography"],
    "出片": ["photography"],
    "冲浪": ["surf", "beach"],
    "潜水": ["beach", "nature"],
    "海岛": ["beach"],
    "夜生活": ["nightlife"],
    "酒吧": ["nightlife"],
    "小众": ["local_life"],
    "本地生活": ["local_life"],
    "手作": ["workshop"],
    "工作坊": ["workshop"],
    "瑜伽": ["wellness"],
    "冥想": ["wellness"],
    "疗愈": ["wellness"],
    "静修": ["wellness"],
}

_NO_SPLIT_KEYWORDS = ["不用分区", "不分区", "整体安排", "一个区域就行", "不用拆", "都在一个区域", "不需要"]
_ALL_REGIONS_KEYWORDS = ["都要", "都去", "全部", "都安排", "所有区域", "都想"]

# Stage-4: incremental-patch extraction. Only these fields can be set via a
# patch ({"updates": {...}}) -- confirmed/region_candidates/region_split_confirmed/
# destination_complexity are managed by other flows (confirmation turn, region
# assessment), never by free-text patch merge.
_PATCH_SCALAR_FIELDS: Dict[str, type] = {
    "departure_city": str, "destination": str, "start_date": str, "end_date": str,
    "duration_days": int, "num_travelers": int, "budget": float, "budget_currency": str,
    "passport_country": str, "visa_status": str, "pace": str, "daily_attraction_count": int,
    "wake_up_time": str, "latest_return_time": str, "special_needs": str,
}
_PATCH_LIST_FIELDS = {
    "interests", "experience_preferences", "region_preferences", "constraints",
    "requested_places", "excluded_places",
}

# Safety net: `pace`/`interests` are closed enumerations the rest of the
# pipeline keys off of verbatim (e.g. `TravelRequirement.apply_defaults()`'s
# `{"特种兵":5,"平衡":3,"松弛":2}.get(self.pace, 3)`); a fast-tier LLM
# occasionally answers in English despite the prompt instruction ("relaxed"
# instead of "松弛"), which would silently degrade to defaults downstream
# instead of raising. Normalize known synonyms, drop anything else.
_PACE_SYNONYMS = {
    "relaxed": "松弛", "chill": "松弛", "slow": "松弛", "leisurely": "松弛",
    "balanced": "平衡", "moderate": "平衡", "normal": "平衡",
    "intense": "特种兵", "packed": "特种兵", "fast": "特种兵", "rushed": "特种兵",
}


class RequirementAgent:
    """Extracts and progressively fills a `TravelRequirement` from chat."""

    def __init__(self) -> None:
        # tier="fast": both call sites (patch extraction, complexity assessment)
        # need low latency; complexity assessment also needs tool-calling, which
        # only the fast tier (deepseek-chat) supports.
        self._llm = get_llm(role="requirement", tier="fast")
        self._system_prompt = load_prompt("requirement_agent")
        self._destination_intelligence = DestinationIntelligenceService()

    def run(
        self,
        user_message: str,
        previous: Optional[TravelRequirement] = None,
        profile_hint: Optional[Dict[str, Any]] = None,
    ) -> RequirementExtractionResult:
        requirement = previous.model_copy(deep=True) if previous else TravelRequirement()

        if self._llm is not None:
            requirement = self._extract_with_llm(user_message, requirement)
        else:
            requirement = self._extract_heuristic(user_message, requirement)

        missing_required = requirement.missing_required_fields()
        is_complete = len(missing_required) == 0

        if is_complete:
            self._apply_profile_hint(requirement, profile_hint)
            requirement.apply_defaults()

        summary = self._build_summary(requirement)
        clarification_question = None
        if not is_complete:
            clarification_question = self._build_clarification_question(missing_required)

        return RequirementExtractionResult(
            requirement=requirement,
            summary=summary,
            confirmed_fields=requirement.confirmed_field_names(),
            missing_fields=missing_required,
            is_complete=is_complete,
            clarification_question=clarification_question,
        )

    # -- LLM path -----------------------------------------------------
    def _extract_with_llm(self, user_message: str, requirement: TravelRequirement) -> TravelRequirement:
        """Stage-4: incremental patch extraction, not full-object regeneration.

        Asks for only the fields mentioned/changed *this turn* as a small plain
        JSON object (no `with_structured_output`/json_schema -- that forces a
        large schema into every call and is the slow part of a "simple" turn),
        then merges the patch onto `requirement` in Python (`_merge_patch`).
        Falls back to the offline heuristic extractor on any parse/LLM failure,
        same contract as before.
        """
        try:
            from datetime import date

            field_names = ", ".join(sorted(set(_PATCH_SCALAR_FIELDS) | _PATCH_LIST_FIELDS))
            prompt = (
                "请阅读用户最新消息，结合已知的旅行需求（JSON），只输出本轮**新增或变更**的字段，"
                "不要重复已知且未被提及的字段，绝不凭空编造用户没有提到的信息。\n\n"
                '严格以如下 JSON 格式返回，不要输出其他文字、不要用代码块包裹：\n'
                '{"updates": {"<字段名>": <值>, ...}}\n\n'
                f"今天的日期是 {date.today().isoformat()}。当用户只说"
                '"X月"这类不含年份的相对日期时，start_date 请按"从今天起下一个未过去的X月"推算'
                "（例如今天是 8 月，用户说"
                '"3月去"，应推算为明年 3 月），格式为 YYYY-MM 或 YYYY-MM-DD。\n'
                f"可用字段名: {field_names}\n"
                f'pace 字段的值只能是这三个中文字符串之一："{PACE_OPTIONS[0]}"/"{PACE_OPTIONS[1]}"/'
                f'"{PACE_OPTIONS[2]}"，不要翻译成英文或其他表述。\n'
                "列表类字段 (interests/experience_preferences/region_preferences/constraints/"
                "requested_places/excluded_places) "
                "只需给出本轮新提到的新增项，不要重复已有项。完全没有新增信息时 updates 为 {}。\n\n"
                f"已知需求: {requirement.model_dump_json()}\n\n"
                f"用户最新消息: {user_message}"
            )
            messages = []
            if self._system_prompt:
                messages.append(("system", self._system_prompt))
            messages.append(("human", prompt))
            resp = self._llm.invoke(messages)
            content = (resp.content or "").strip()
            if content.startswith("```"):
                content = content.strip("`")
                content = content.split("\n", 1)[-1] if "\n" in content else content
            parsed = json.loads(content)
            updates = parsed.get("updates") if isinstance(parsed, dict) else None
            if isinstance(updates, dict):
                return self._merge_patch(requirement, updates)
        except Exception:
            pass
        # Fall back to heuristic if the LLM call fails for any reason.
        return self._extract_heuristic(user_message, requirement)

    def _merge_patch(self, requirement: TravelRequirement, updates: Dict[str, Any]) -> TravelRequirement:
        """Apply a `{"updates": {...}}` patch onto `requirement`.

        Scalar fields: new value wins if present/non-empty (same "prefer new"
        semantics as the old full-object merge). List fields: treated as
        *additions* (append + dedupe), since the LLM is now only asked to
        report what's newly mentioned, not the full history -- unlike the old
        full-object output, a patch's list value isn't the complete list.
        Unknown/hallucinated field names are silently dropped.
        """
        merged = requirement.model_dump()
        pace_was_updated = False
        for key, value in updates.items():
            if key in _PATCH_LIST_FIELDS:
                if not isinstance(value, list):
                    continue
                existing = list(merged.get(key) or [])
                for item in value:
                    if isinstance(item, str) and item not in existing:
                        existing.append(item)
                merged[key] = existing
            elif key in _PATCH_SCALAR_FIELDS:
                if value in (None, ""):
                    continue
                if key == "pace":
                    normalized = _PACE_SYNONYMS.get(str(value).strip().lower(), value)
                    if normalized not in PACE_OPTIONS:
                        continue
                    merged[key] = normalized
                    pace_was_updated = True
                    continue
                py_type = _PATCH_SCALAR_FIELDS[key]
                try:
                    merged[key] = py_type(value)
                except (TypeError, ValueError):
                    continue
        if pace_was_updated and "daily_attraction_count" not in updates:
            merged["daily_attraction_count"] = {"特种兵": 5, "平衡": 3, "松弛": 2}.get(merged.get("pace"), 3)
            merged["wake_up_time"] = "07:30" if merged.get("pace") == "特种兵" else "08:30"
            merged["latest_return_time"] = "23:00" if merged.get("pace") == "特种兵" else "21:30"
        return TravelRequirement(**merged)

    # -- Heuristic (offline) path --------------------------------------
    def _extract_heuristic(self, user_message: str, requirement: TravelRequirement) -> TravelRequirement:
        text = user_message.strip()

        # destination: "去X" / "到X" -- lookahead stops at punctuation/digits/common
        # trip-suffix words ("玩"/"游"/"旅游"...) without consuming them, so the
        # captured city name doesn't swallow trailing filler words.
        m = re.search(r"[去到]([一-龥]{2,6}?)(?=[，,。\d]|玩|游玩|旅游|旅行|度假|自由行|$)", text)
        if m and not requirement.destination:
            requirement.destination = m.group(1)

        # duration days: "X天"
        m = re.search(r"(\d+)\s*天", text)
        if m:
            requirement.duration_days = int(m.group(1))

        # month / rough start date: "X月"
        m = re.search(r"(\d{1,2})\s*月", text)
        if m:
            month = int(m.group(1))
            from datetime import datetime
            year = datetime.now().year
            if month < datetime.now().month:
                year += 1
            requirement.start_date = f"{year}-{month:02d}"

        # num_travelers: "两个人" / "2人" / "3位"
        m = re.search(r"(\d+)\s*[人位口个]", text)
        if m:
            requirement.num_travelers = int(m.group(1))
        else:
            for cn, val in _CN_NUM.items():
                if re.search(cn + r"个?人", text):
                    requirement.num_travelers = val
                    break

        # budget: "预算X元/万/块"
        m = re.search(r"预算\s*(\d+(?:\.\d+)?)\s*万", text)
        if m:
            requirement.budget = float(m.group(1)) * 10000
        else:
            m = re.search(r"预算\s*(\d+(?:\.\d+)?)\s*[元块]?", text)
            if m:
                requirement.budget = float(m.group(1))

        # departure city: "从X出发" / "X出发"
        m = re.search(r"从([一-龥]{2,6})出发", text)
        if m:
            requirement.departure_city = m.group(1)

        # pace
        for pace, keywords in _PACE_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                requirement.pace = pace
                break
        if requirement.pace is None and any(kw in text for kw in _PACE_KEYWORDS.get("特种兵", [])):
            requirement.pace = "特种兵"

        # interests
        found_interests: List[str] = list(requirement.interests)
        for interest, synonyms in _INTEREST_SYNONYMS.items():
            if any(s in text for s in synonyms) and interest not in found_interests:
                found_interests.append(interest)
        requirement.interests = found_interests

        # experience_preferences: finer-grained tags than `interests` (e.g. "潮流
        # 文化" -> fashion/street_culture/local_life, not just "购物").
        found_experience: List[str] = list(requirement.experience_preferences)
        for keyword, tags in _EXPERIENCE_KEYWORD_MAP.items():
            if keyword in text.lower() or keyword in text:
                for tag in tags:
                    if tag not in found_experience:
                        found_experience.append(tag)
        requirement.experience_preferences = found_experience

        # The P0 preference confirmation always labels these two fields.
        # Keep them separate from region selection: "大熊猫、春熙路、太古里"
        # are requested POIs, not three geographic regions to fan out into.
        def _labelled_places(label: str) -> List[str]:
            match = re.search(rf"{label}\s*[：:]\s*([^；;。]+)", text)
            if not match:
                return []
            value = match.group(1).strip()
            if not value or any(word in value for word in ("没有", "无指定", "可留空")):
                return []
            return [part.strip() for part in re.split(r"[、,，/]|和|以及", value) if part.strip()]

        for name in _labelled_places("必去"):
            if name not in requirement.requested_places:
                requirement.requested_places.append(name)
        for name in _labelled_places("不想去"):
            if name not in requirement.excluded_places:
                requirement.excluded_places.append(name)

        # explicit constraints (dietary/accessibility/pace-related asks that
        # aren't covered by the structured fields above)
        constraint_keywords = ["素食", "清真", "过敏", "无麸质", "轮椅", "不要早起", "不吃"]
        found_constraints = list(requirement.constraints)
        for kw in constraint_keywords:
            if kw in text and kw not in found_constraints:
                found_constraints.append(kw)
        requirement.constraints = found_constraints

        # special needs
        if any(k in text for k in ["老人", "长辈", "父母"]):
            requirement.special_needs = (requirement.special_needs or "") + " 有老人同行，需照顾体力与节奏。"
        if any(k in text for k in ["小孩", "儿童", "孩子", "宝宝"]):
            requirement.special_needs = (requirement.special_needs or "") + " 有儿童同行，需安排适合亲子的行程。"

        return requirement

    # -- Presentation helpers -------------------------------------------
    def _build_summary(self, r: TravelRequirement) -> str:
        parts = []
        if r.departure_city and r.departure_city != "未指定":
            parts.append(f"出发地: {r.departure_city}")
        if r.destination:
            parts.append(f"目的地: {r.destination}")
        if r.start_date:
            parts.append(f"出行时间: {r.start_date}" + (f" 起 {r.duration_days} 天" if r.duration_days else ""))
        elif r.duration_days:
            parts.append(f"行程天数: {r.duration_days} 天")
        if r.num_travelers:
            parts.append(f"出行人数: {r.num_travelers} 人")
        if r.budget:
            parts.append(f"预算: {r.budget:.0f} {r.budget_currency}")
        if r.pace:
            parts.append(f"旅行节奏: {r.pace}")
        if r.interests:
            parts.append(f"兴趣偏好: {', '.join(r.interests)}")
        if r.experience_preferences:
            parts.append(f"细分体验偏好: {', '.join(r.experience_preferences)}")
        if r.requested_places:
            parts.append(f"必去地点: {', '.join(r.requested_places)}")
        if r.excluded_places:
            parts.append(f"不想去: {', '.join(r.excluded_places)}")
        if r.region_preferences:
            parts.append(f"区域安排: {', '.join(r.region_preferences)}")
        if r.daily_attraction_count:
            parts.append(f"每日景点数: {r.daily_attraction_count}")
        if r.wake_up_time:
            parts.append(f"起床时间: {r.wake_up_time}")
        if r.latest_return_time:
            parts.append(f"最晚返回酒店: {r.latest_return_time}")
        if r.special_needs:
            parts.append(f"特殊需求: {r.special_needs.strip()}")
        return "；".join(parts) if parts else "暂未提取到有效信息。"

    def _build_clarification_question(self, missing_required: List[str]) -> str:
        field_names_cn = {
            "destination": "目的地",
            "trip_length_known": "出行天数或起止日期",
            "num_travelers": "出行人数",
            "budget": "预算",
            "pace": "旅行节奏（特种兵/平衡/松弛）",
        }
        missing_cn = [field_names_cn.get(f, f) for f in missing_required]
        return "为了帮您规划行程，还需要补充以下信息：" + "、".join(missing_cn) + "。"

    # -- Stage-2: soft personalization from L3 profile memory -----------
    def _apply_profile_hint(self, requirement: TravelRequirement, profile_hint: Optional[Dict[str, Any]]) -> None:
        """Seed *missing* optional fields from a returning user's L3 profile.

        Never overwrites anything the user actually said this trip (only
        touches fields that are still empty), and never touches hard facts
        like destination/dates/budget.
        """
        if not profile_hint:
            return
        interest_preference = profile_hint.get("interest_preference") or []
        if not requirement.interests and interest_preference:
            requirement.interests = [i for i in interest_preference if i in INTEREST_OPTIONS][:3] or requirement.interests
        if not requirement.experience_preferences and interest_preference:
            from travel_agent.schemas.experience import EXPERIENCE_TYPES

            requirement.experience_preferences = [i for i in interest_preference if i in EXPERIENCE_TYPES]

    # -- Stage-2: destination complexity / region confirmation -----------
    # Round-5: delegates to DestinationIntelligenceService (moved verbatim
    # from this method -- same known-destination table, same LLM prompt
    # shape, same confirmation-message text), which also owns the new
    # ad-hoc single-region `profile_region()` entry point used by the
    # post-plan region-replacement flow (see execution/agent_router.py).
    def assess_destination_complexity(self, req: TravelRequirement) -> DestinationComplexityAssessment:
        """Decide whether `req.destination` should be offered a region split."""
        return self._destination_intelligence.assess_region_split(
            req.destination or "", llm=self._llm, system_prompt=self._system_prompt
        )

    def parse_region_selection(self, message: str, assessment: DestinationComplexityAssessment) -> List[str]:
        """Return the list of region names the user confirmed (empty = no split)."""
        text = (message or "").strip()
        if not assessment.regions:
            return []
        if any(k in text for k in _NO_SPLIT_KEYWORDS):
            return []
        region_names = [r.name for r in assessment.regions]
        if not text or any(k in text for k in _ALL_REGIONS_KEYWORDS):
            return region_names
        mentioned = [name for name in region_names if self._region_is_mentioned(text, name)]
        return mentioned or region_names

    @staticmethod
    def _region_is_mentioned(text: str, region_name: str) -> bool:
        """Match both the full display label and its human-friendly parts.

        Region labels shown by the UI include explanatory suffixes such as
        ``涩谷·新宿·原宿（西东京潮流区）``.  Users naturally answer with the
        visible place names rather than copying that whole label, so exact
        matching incorrectly treated a three-region choice as "all regions".
        """
        haystack = (text or "").lower()
        label = (region_name or "").lower()
        if label and label in haystack:
            return True
        core = re.split(r"[（(]", label, maxsplit=1)[0]
        aliases = [part.strip() for part in re.split(r"[·・、/／]", core) if len(part.strip()) >= 2]
        return any(alias in haystack for alias in aliases)

    def parse_region_correction(
        self,
        message: str,
        current_regions: List[str],
        assessment: DestinationComplexityAssessment,
    ) -> List[str]:
        """Apply an explicit region correction during requirement confirmation.

        Supports the common conversational forms "不要台场", "去掉乌布",
        "改成浅草和银座" and "只保留……".  Returns the original list when
        the message does not clearly discuss a known region.
        """
        text = (message or "").strip()
        if not text or not assessment.regions:
            return list(current_regions)
        region_names = [region.name for region in assessment.regions]

        if any(keyword in text for keyword in _NO_SPLIT_KEYWORDS):
            return []

        keep_marker = "只保留"
        if keep_marker in text:
            keep_text = text.split(keep_marker, 1)[1]
            kept = [name for name in region_names if self._region_is_mentioned(keep_text, name)]
            if kept:
                return kept

        mentioned = [name for name in region_names if self._region_is_mentioned(text, name)]
        if not mentioned:
            return list(current_regions)
        if any(word in text for word in ("不要", "去掉", "删除", "移除", "排除")):
            return [name for name in current_regions if name not in mentioned]
        if any(word in text for word in ("改成", "改为", "换成", "只去", "重新选")):
            return mentioned
        return list(current_regions)
