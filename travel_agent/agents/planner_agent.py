"""Planner Agent: turns the confirmed requirement + selected experiences +
research result into a day-by-day `Itinerary`.

Stage-2: Hierarchical Planner, three explicit stages:
  1. Region Planning   (`_plan_regions`)      -- which days go to which region.
  2. Experience Planning (`_partition_by_region` + the day-building loop) --
     a type-balanced daily mix (culture/nature/shopping/food/rest) drawn from
     that day's region-scoped pool.
  3. Timeline Planning (`_build_day`)         -- minute-by-minute schedule,
     every transition backed by the real `calculate_route` tool.

Also new: `check_feasibility`, called before any of the above. If the
selected pool is too thin for the trip length, the Planner refuses to
hard-generate a threadbare itinerary -- it returns `PlanFeasibility(status=
"insufficient", ...)` instead, and the graph loops back to the Research
Orchestrator for a targeted expansion (see `graph/nodes.py`).

The day-by-day scheduling algorithm itself stays deterministic (letting the
Reviewer's hard rule checks and the demo stay reliable); the LLM, when
configured, is used only to rewrite each item's `reason` into a more natural
sentence grounded in the real place data gathered by Research -- never to
invent times, costs or routes.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from travel_agent.config.llm import get_llm
from travel_agent.prompts_loader import load_prompt
from travel_agent.schemas.itinerary import DayPlan, Itinerary, ItineraryItem, PlanFeasibility
from travel_agent.schemas.research_result import ResearchResult
from travel_agent.schemas.travel_requirement import TravelRequirement
from travel_agent.tool_runtime import get_tool_manager
from travel_agent.tools.amap_routes import calculate_route
from travel_agent.utils.logging import get_logger

_logger = get_logger("travel_agent.agents.planner")

_MODE_LABELS = {"WALK": "步行", "TRANSIT": "公共交通", "DRIVE": "驾车"}
_INTEREST_TO_TYPE = {"购物": "shopping", "美食": "food", "人文": "culture", "自然": "nature", "摄影": "photography"}


def _place_fields(experience: Dict[str, Any]) -> Dict[str, Any]:
    """Keep provider identity and GCJ-02 coordinates through planning."""
    return {
        "place_id": experience.get("place_id"),
        "latitude": experience.get("latitude"),
        "longitude": experience.get("longitude"),
        "rating": experience.get("rating"),
        "name": experience.get("name"),
        "item_type": "restaurant" if experience.get("type") == "food" else experience.get("type"),
        "place_details_status": "VERIFIED" if experience.get("place_id") else "UNKNOWN",
    }


def _hhmm_to_minutes(hhmm: str) -> int:
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 8 * 60


def _minutes_to_hhmm(minutes: int) -> str:
    minutes = minutes % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _name_key(value: Any) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]", "", str(value or "")).lower()


def _matches_required(item: dict, required_names: List[str]) -> bool:
    item_name = _name_key(item.get("name"))
    if not item_name:
        return False
    aliases = {"杭钢": "杭州钢铁"}
    for name in required_names:
        key = _name_key(name)
        expanded = aliases.get(key[:2], "") + key[2:] if key.startswith("杭钢") else key
        alias_match = key.startswith("杭钢") and "杭州钢铁" in item_name
        if key and (key in item_name or item_name in key or (expanded and expanded in item_name) or alias_match):
            return True
    return False


def _nearest_candidate(pool: List[dict], origin: Optional[dict]) -> Optional[dict]:
    if not pool:
        return None
    if origin and origin.get("latitude") is not None and origin.get("longitude") is not None:
        lat, lon = float(origin["latitude"]), float(origin["longitude"])
        located = [row for row in pool if row.get("latitude") is not None and row.get("longitude") is not None]
        if located:
            chosen = min(located, key=lambda row: (float(row["latitude"]) - lat) ** 2 + (float(row["longitude"]) - lon) ** 2)
            pool.remove(chosen)
            return chosen
    return pool.pop(0)


def _spread_required(items: List[dict], day_numbers: List[int], daily_count: int) -> Dict[int, List[dict]]:
    distributed = {day: [] for day in day_numbers}
    if not day_numbers:
        return distributed
    slots_per_day = max(1, daily_count)
    for index, item in enumerate(items):
        day_index = min(index // slots_per_day, len(day_numbers) - 1)
        distributed[day_numbers[day_index]].append(item)
    return distributed


_FALLBACK_MODE = {"transit": "drive", "drive": "transit", "walk": "drive"}


def _route(origin: str, destination: str, mode: str) -> Dict[str, Any]:
    """Wrap `calculate_route`: real duration + a Chinese mode label.

    Some regions have no TRANSIT routing coverage at all -- if the requested
    mode returns no route, retry once with a real alternate mode before
    falling back to a flat estimate, so we still surface an actual measured
    travel time whenever possible.
    """
    result = get_tool_manager().call(
        calculate_route,
        {"origin": origin, "destination": destination, "mode": mode},
        tool_name="amap_routes.calculate_route",
    )
    if not result.get("success", True):
        alt_mode = _FALLBACK_MODE.get(mode.lower())
        if alt_mode:
            _logger.info("route lookup failed for mode=%s (%s -> %s), retrying with %s", mode, origin, destination, alt_mode)
            result = get_tool_manager().call(
                calculate_route,
                {"origin": origin, "destination": destination, "mode": alt_mode},
                tool_name="amap_routes.calculate_route",
            )

    if result.get("success", True):
        label = _MODE_LABELS.get(str(result.get("mode", "")).upper(), result.get("mode", mode))
        return {"duration_minutes": max(5, round(result["duration_minutes"])), "label": label}

    _logger.warning("route lookup failed (%s -> %s): %s", origin, destination, result.get("error"))
    fallback_label = _MODE_LABELS.get(mode.upper(), mode)
    return {"duration_minutes": 30, "label": f"{fallback_label}(路线数据获取失败，用时为预估)"}


class PlannerAgent:
    def __init__(self) -> None:
        # tier="fast": short constrained-output reason polishing -- see
        # `config/llm.py` docstring for why "deep" isn't used by default here.
        self._llm = get_llm(role="planner", tier="fast")
        self._system_prompt = load_prompt("planner_agent")

    # -- Pre-generation check: refuse to hard-generate a thin itinerary ----
    def check_feasibility(self, requirement: TravelRequirement, selected_experiences: List[dict]) -> PlanFeasibility:
        days = requirement.duration_days or 5
        daily_count = requirement.daily_attraction_count or 3
        non_food = [e for e in selected_experiences if e.get("type") != "food"]
        food = [e for e in selected_experiences if e.get("type") == "food"]
        target_non_food = max(daily_count * days, 3)
        target_food = max(days * 2, 2)

        missing_categories: List[str] = []
        if len(non_food) < target_non_food:
            present_types = {e.get("type") for e in non_food}
            wanted_types: List[str] = list(requirement.experience_preferences or [])
            wanted_types += [_INTEREST_TO_TYPE[i] for i in (requirement.interests or []) if i in _INTEREST_TO_TYPE]
            under_represented = [t for t in dict.fromkeys(wanted_types) if t not in present_types]
            missing_categories.extend(under_represented or ["experience"])
        if len(food) < target_food:
            missing_categories.append("food")

        if not missing_categories:
            return PlanFeasibility(status="sufficient")

        total_needed = target_non_food + target_food
        reason = f"活动数量不足：本次行程共需约 {total_needed} 项体验，当前仅有 {len(selected_experiences)} 项。"
        return PlanFeasibility(status="insufficient", reason=reason, missing_categories=missing_categories)

    # -- Stage 1: Region Planning ---------------------------------------
    def _plan_regions(self, requirement: TravelRequirement) -> List[Dict[str, Any]]:
        days = max(requirement.duration_days or 5, 1)
        regions: List[Optional[str]] = (
            list(requirement.region_preferences)
            if (requirement.region_split_confirmed and requirement.region_preferences)
            else [None]
        )
        n = min(len(regions), days) or 1
        regions = regions[:n]
        base, remainder = divmod(days, n)

        allocations: List[Dict[str, Any]] = []
        day_counter = 1
        for i, region in enumerate(regions):
            count = base + (1 if i < remainder else 0)
            if count <= 0:
                continue
            allocations.append({"region": region, "days": list(range(day_counter, day_counter + count))})
            day_counter += count
        return allocations

    @staticmethod
    def _partition_by_region(experiences: List[dict]) -> Dict[Optional[str], List[dict]]:
        pools: Dict[Optional[str], List[dict]] = {}
        for e in experiences:
            pools.setdefault(e.get("region"), []).append(e)
        return pools

    def _preferred_mode(self, profile_hint: Optional[Dict[str, Any]]) -> str:
        pref = str((profile_hint or {}).get("transport_preference") or "")
        if "驾车" in pref or "高效" in pref:
            return "drive"
        return "transit"

    # -- Stages 2+3: Experience Planning + Timeline Planning, per day ----
    def _next_from_pools(self, region_pool: List[dict], fallback_pool: List[dict]) -> Optional[dict]:
        if region_pool:
            return region_pool.pop(0)
        if fallback_pool:
            return fallback_pool.pop(0)
        return None

    def _build_day(
        self,
        day_number: int,
        region: Optional[str],
        requirement: TravelRequirement,
        non_food_pool: List[dict],
        non_food_fallback: List[dict],
        food_pool: List[dict],
        food_fallback: List[dict],
        transport_mode: str,
        required_pool: Optional[List[dict]] = None,
    ) -> DayPlan:
        daily_count = max(requirement.daily_attraction_count or 3, len(required_pool or []))
        wake = _hhmm_to_minutes(requirement.wake_up_time or "08:30")
        latest_return = _hhmm_to_minutes(requirement.latest_return_time or "21:30")
        num_travelers = requirement.num_travelers or 1

        items: List[ItineraryItem] = []
        current_location = "酒店"
        current_experience: Optional[dict] = None
        t = wake

        items.append(
            ItineraryItem(
                time=_minutes_to_hhmm(t), activity="breakfast", location=f"酒店/附近早餐店（第{day_number}天）", transport="步行",
                duration_minutes=45, estimated_cost=40 * num_travelers, reason="在酒店附近简单用早餐，为一天行程做准备。",
            )
        )
        t += 45 + 15

        morning_n = math.ceil(daily_count / 2)
        afternoon_n = daily_count - morning_n

        def _add_experience(t: int, current_location: str) -> Tuple[int, str]:
            nonlocal current_experience
            e = required_pool.pop(0) if required_pool else self._next_from_pools(non_food_pool, non_food_fallback)
            if e is None:
                return t, current_location
            route = _route(current_location, e["location"], transport_mode)
            items.append(
                ItineraryItem(
                    time=_minutes_to_hhmm(t), activity="attraction", location=f"{e['name']} ({e['location']})",
                    transport=f"{route['label']} 约{route['duration_minutes']}分钟",
                    transport_duration_minutes=route["duration_minutes"],
                    duration_minutes=e.get("duration_minutes", 90), estimated_cost=(e.get("cost") or 0) * num_travelers,
                    reason="；".join(e.get("advantages", [])[:2]) or f"符合您的兴趣偏好（{e.get('type', '')}）。",
                    region=e.get("region") or region,
                    **_place_fields(e),
                )
            )
            current_experience = e
            return t + e.get("duration_minutes", 90) + route["duration_minutes"], e["location"]

        for _ in range(morning_n):
            t, current_location = _add_experience(t, current_location)

        lunch_t = max(t, wake + 4 * 60, 12 * 60)
        meal = _nearest_candidate(food_pool if food_pool else food_fallback, current_experience) or {
            "name": "当地特色餐厅", "cost": 100, "location": requirement.destination, "type": "food",
        }
        route = _route(current_location, meal.get("location", requirement.destination), transport_mode)
        items.append(
            ItineraryItem(
                time=_minutes_to_hhmm(lunch_t), activity="lunch", location=meal["name"],
                transport=f"{route['label']} 约{route['duration_minutes']}分钟", duration_minutes=75,
                transport_duration_minutes=route["duration_minutes"],
                estimated_cost=(meal.get("cost") or 100) * num_travelers,
                reason="；".join(meal.get("advantages", [])[:2]) or "当地推荐餐厅。",
                **_place_fields(meal),
            )
        )
        t = lunch_t + 75 + 15
        current_location = meal.get("location", requirement.destination)
        current_experience = meal

        for _ in range(afternoon_n):
            t, current_location = _add_experience(t, current_location)

        dinner_t = max(t, lunch_t + 4 * 60, 18 * 60)
        meal = _nearest_candidate(food_pool if food_pool else food_fallback, current_experience) or {
            "name": "当地特色餐厅", "cost": 100, "location": requirement.destination, "type": "food",
        }
        route = _route(current_location, meal.get("location", requirement.destination), transport_mode)
        items.append(
            ItineraryItem(
                time=_minutes_to_hhmm(dinner_t), activity="dinner", location=meal["name"],
                transport=f"{route['label']} 约{route['duration_minutes']}分钟", duration_minutes=90,
                transport_duration_minutes=route["duration_minutes"],
                estimated_cost=(meal.get("cost") or 100) * num_travelers,
                reason="；".join(meal.get("advantages", [])[:2]) or "当地推荐餐厅，结束一天行程。",
                **_place_fields(meal),
            )
        )
        t = dinner_t + 90
        current_location = meal.get("location", requirement.destination)

        if "购物" in (requirement.interests or []) and t + 60 <= latest_return:
            items.append(
                ItineraryItem(
                    time=_minutes_to_hhmm(t), activity="shopping", location=f"{requirement.destination}商业区",
                    transport="步行/地铁", duration_minutes=min(90, latest_return - t), estimated_cost=0,
                    reason="您偏好购物，安排晚间自由购物时间。",
                )
            )
            t += min(90, latest_return - t)

        if _minutes_to_hhmm(t) != requirement.latest_return_time:
            items.append(
                ItineraryItem(
                    time=_minutes_to_hhmm(min(t, latest_return)), activity="return_to_hotel", location="酒店",
                    transport="地铁/出租车", duration_minutes=30, estimated_cost=0, reason="返回酒店休息。",
                )
            )

        for item in items:
            if item.region is None:
                item.region = region
            if item.city is None:
                item.city = requirement.destination

        return DayPlan(day_number=day_number, items=items, city=requirement.destination, accommodation="hotel")

    # -- Stage-3: rebuild only specific days, copying the rest verbatim -----
    def _rebuild_days(
        self,
        requirement: TravelRequirement,
        previous_itinerary: Itinerary,
        selected_experiences: List[dict],
        target_days: List[int],
        profile_hint: Optional[Dict[str, Any]] = None,
        region_overrides: Optional[Dict[int, Optional[str]]] = None,
    ) -> Itinerary:
        target_set = set(target_days)

        # Never re-place something already scheduled on an untouched day.
        already_used = set()
        previously_scheduled_anywhere = set()
        for day in previous_itinerary.days:
            for item in day.items:
                if item.activity in ("attraction", "lunch", "dinner"):
                    previously_scheduled_anywhere.add(item.location.split(" (")[0])
                    if day.day_number not in target_set:
                        already_used.add(item.location.split(" (")[0])

        non_food_all = [e for e in selected_experiences if e.get("type") != "food" and e.get("name") not in already_used]
        food_all = [e for e in selected_experiences if e.get("type") == "food" and e.get("name") not in already_used]
        required_pool = [e for e in non_food_all if _matches_required(e, requirement.requested_places or [])]
        non_food_all = [e for e in non_food_all if e not in required_pool]

        # Brand-new candidates (never scheduled anywhere in the previous
        # itinerary -- e.g. what Research just added because the user asked
        # for more of some category) go to the front of the pool, ahead of
        # previously-scheduled-but-now-freed-up items. Otherwise a stale FIFO
        # ordering can silently favor old leftovers and never actually place
        # the new thing the user asked for.
        def _new_first(e: dict) -> int:
            return 0 if e.get("name") not in previously_scheduled_anywhere else 1

        non_food_all.sort(key=_new_first)
        food_all.sort(key=_new_first)

        non_food_pools = self._partition_by_region(non_food_all)
        food_pools = self._partition_by_region(food_all)
        non_food_fallback = non_food_pools.pop(None, [])
        food_fallback = food_pools.pop(None, [])
        transport_mode = self._preferred_mode(profile_hint)

        region_by_day: Dict[int, Optional[str]] = {}
        for allocation in self._plan_regions(requirement):
            for day_num in allocation["days"]:
                region_by_day[day_num] = allocation["region"]
        if not requirement.region_split_confirmed and non_food_pools:
            discovered_regions = list(non_food_pools)
            for day_num in range(1, (requirement.duration_days or 1) + 1):
                region_by_day[day_num] = discovered_regions[(day_num - 1) % len(discovered_regions)]
        if region_overrides:
            # Per-day override wins over the global split -- and, critically,
            # `requirement.region_preferences` itself is never touched, so a
            # later full replan isn't polluted by this one-off swap.
            region_by_day.update(region_overrides)

        required_by_day = _spread_required(required_pool, sorted(target_set), requirement.daily_attraction_count or 3)

        rebuilt_days: List[DayPlan] = []
        for day in previous_itinerary.days:
            if day.day_number not in target_set:
                rebuilt_days.append(day)
                continue
            region = region_by_day.get(day.day_number)
            rebuilt_days.append(
                self._build_day(
                    day.day_number, region, requirement,
                    non_food_pools.get(region, []), non_food_fallback,
                    food_pools.get(region, []), food_fallback, transport_mode,
                    required_by_day.get(day.day_number, []),
                )
            )
        return Itinerary(days=sorted(rebuilt_days, key=lambda d: d.day_number))

    def run_partial(
        self,
        requirement: TravelRequirement,
        previous_itinerary: Itinerary,
        research: ResearchResult,
        selected: Dict[str, List[dict]],
        target_days: List[int],
        target_time_periods: Optional[List[str]] = None,
        profile_hint: Optional[Dict[str, Any]] = None,
        region_overrides: Optional[Dict[int, Optional[str]]] = None,
    ) -> Itinerary:
        """Design doc XIII/XIV: rebuild ONLY `target_days`, copying every
        other day verbatim from `previous_itinerary` -- this is what makes
        "其他天不要动" an actual guarantee rather than a promise in the reply
        text. Day-level granularity: `target_time_periods` is accepted and
        recorded by the caller (execution_planner/aggregator) for a future
        refinement into within-day segment preservation, but this pass
        rebuilds the whole target day.

        `region_overrides` (Round-5): `{day_number: region_name}` -- pins a
        specific rebuilt day to a specific region (e.g. a mid-trip "replace
        Ubud with Nusa Penida" swap) without touching
        `requirement.region_preferences`, the global/persisted split. See
        `_rebuild_days`."""
        selected_experiences = list(selected.get("experiences", [])) if selected else []
        itinerary = self._rebuild_days(
            requirement, previous_itinerary, selected_experiences, target_days, profile_hint,
            region_overrides=region_overrides,
        )
        if self._llm is not None:
            self._refine_reasons_with_llm(itinerary)
        return itinerary

    # -- Public API -------------------------------------------------------
    def run(
        self,
        requirement: TravelRequirement,
        selected: Dict[str, List[dict]],
        research: ResearchResult,
        revision_instruction: Optional[List[str]] = None,
        rule_issues: Optional[List[str]] = None,
        loop_count: int = 0,
        profile_hint: Optional[Dict[str, Any]] = None,
        previous_itinerary: Optional[Itinerary] = None,
    ) -> Tuple[Itinerary, PlanFeasibility]:
        """Returns `(itinerary, feasibility)`. The itinerary is *always* built
        (even when `feasibility.status == "insufficient"`) so a graph that has
        exhausted its expansion-loop budget can still fall back to a
        best-effort plan instead of stalling; the caller decides whether to
        use it immediately or loop back to Research first.

        Stage-3: when `previous_itinerary` is given (a reviewer-loop revision)
        and the Rule Validator's `rule_issues` are all traceable to specific
        days (they're prefixed "第N天 ..."), and nothing here requires a
        budget-wide re-sort (which touches every day's cost), only THOSE days
        get rebuilt on top of the previous plan. Without this, every review
        loop reconstructed the whole trip from the same original pool with
        the same static heuristics, so loop 2/3 typically reproduced loop 1's
        output near-verbatim instead of actually improving on it.
        """
        selected_experiences = list(selected.get("experiences", [])) if selected else []
        feasibility = self.check_feasibility(requirement, selected_experiences)

        instructions_text = " ".join(revision_instruction or [])
        prefer_cheap = any(k in instructions_text for k in ["超预算", "预算", "budget"])
        reorder_by_location = any(k in instructions_text for k in ["路程", "路线效率", "路线"])
        if any(k in instructions_text for k in ["景点数量", "过于疲劳", "疲劳", "时间不足", "冲突"]):
            requirement = requirement.model_copy(update={"daily_attraction_count": max(1, (requirement.daily_attraction_count or 3) - 1)})

        day_numbers = sorted({int(m) for m in re.findall(r"第(\d+)天", " ".join(rule_issues or []))})
        if previous_itinerary is not None and day_numbers and not prefer_cheap:
            itinerary = self._rebuild_days(requirement, previous_itinerary, selected_experiences, day_numbers, profile_hint)
            if self._llm is not None:
                self._refine_reasons_with_llm(itinerary)
            return itinerary, feasibility

        non_food_all = [e for e in selected_experiences if e.get("type") != "food"]
        food_all = [e for e in selected_experiences if e.get("type") == "food"]
        required_pool = [e for e in non_food_all if _matches_required(e, requirement.requested_places or [])]
        non_food_all = [e for e in non_food_all if e not in required_pool]
        if prefer_cheap:
            non_food_all.sort(key=lambda e: e.get("cost") or 0)
            food_all.sort(key=lambda e: e.get("cost") or 0)
        if reorder_by_location:
            non_food_all.sort(key=lambda e: e.get("location", ""))

        non_food_pools = self._partition_by_region(non_food_all)
        food_pools = self._partition_by_region(food_all)
        non_food_fallback = non_food_pools.pop(None, [])
        food_fallback = food_pools.pop(None, [])
        transport_mode = self._preferred_mode(profile_hint)

        region_allocations = self._plan_regions(requirement)
        if not requirement.region_split_confirmed and non_food_pools:
            discovered_regions = list(non_food_pools)
            region_allocations = [
                {"region": discovered_regions[(day_num - 1) % len(discovered_regions)], "days": [day_num]}
                for day_num in range(1, (requirement.duration_days or 1) + 1)
            ]
        required_by_day = _spread_required(
            required_pool,
            list(range(1, (requirement.duration_days or 1) + 1)),
            requirement.daily_attraction_count or 3,
        )
        day_plans: List[DayPlan] = []
        for allocation in region_allocations:
            region = allocation["region"]
            region_non_food = non_food_pools.get(region, [])
            region_food = food_pools.get(region, [])
            for day_num in allocation["days"]:
                day_plans.append(
                    self._build_day(
                        day_num, region, requirement, region_non_food, non_food_fallback,
                        region_food, food_fallback, transport_mode,
                        required_by_day.get(day_num, []),
                    )
                )

        itinerary = Itinerary(days=sorted(day_plans, key=lambda d: d.day_number))
        if self._llm is not None:
            self._refine_reasons_with_llm(itinerary)
        return itinerary, feasibility

    def _refine_reasons_with_llm(self, itinerary: Itinerary) -> None:
        """Rewrite attraction/meal `reason` text into a natural sentence via LLM.

        Grounded strictly in the item's own (real) name/location/existing
        reason text -- never introduces new facts, times or costs. On any
        failure the original rule-based reasons are left untouched.
        """
        targets = [item for day in itinerary.days for item in day.items if item.activity in ("attraction", "lunch", "dinner")]
        if not targets:
            return

        payload = [{"index": i, "activity": t.activity, "location": t.location, "notes": t.reason} for i, t in enumerate(targets)]
        messages = []
        if self._system_prompt:
            messages.append(("system", self._system_prompt))
        messages.append((
            "human",
            "请把下面每一项行程的 notes 改写成一句更自然的中文推荐理由（不超过40字），"
            "只能使用给定的 location/notes 信息，不要编造新的事实、价格或时间。"
            '严格以 JSON 数组返回，形如 [{"index":0,"reason":"..."}, ...]，不要输出其他文字。\n'
            f"{json.dumps(payload, ensure_ascii=False)}",
        ))

        try:
            resp = self._llm.invoke(messages)
            content = (resp.content or "").strip()
            if content.startswith("```"):
                content = content.strip("`")
                content = content.split("\n", 1)[-1] if "\n" in content else content
            refined = json.loads(content)
            reason_by_index = {r["index"]: r["reason"] for r in refined if "index" in r and r.get("reason")}
            for i, item in enumerate(targets):
                if i in reason_by_index:
                    item.reason = reason_by_index[i]
        except Exception as exc:  # noqa: BLE001 - keep rule-based reasons on any failure
            _logger.warning("LLM reason refinement failed, keeping rule-based text: %s", exc)
