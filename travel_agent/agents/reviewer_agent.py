"""Reviewer Agent: Rule-based Validator + LLM Reviewer.

The rule validator checks hard constraints (time conflicts, opening hours,
budget, attraction count, duplicates). The LLM reviewer (or a heuristic
fallback when no LLM is configured) scores softer dimensions (preference
match, richness, fatigue). The two are combined into a single
`ReviewReport` that the graph uses to decide whether to loop back to the
Planner or proceed to Final Output.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from travel_agent.config.llm import get_llm
from travel_agent.config.settings import get_settings
from travel_agent.prompts_loader import load_prompt
from travel_agent.schemas.itinerary import Itinerary
from travel_agent.schemas.research_result import ResearchResult
from travel_agent.schemas.review import DimensionScores, ReviewReport
from travel_agent.schemas.travel_requirement import TravelRequirement

# Synthetic/generic location text the Planner itself generates when no real
# candidate is available (e.g. the fallback "当地特色餐厅") -- never a fact
# error, just a known placeholder.
_GENERIC_LOCATION_MARKERS = ["酒店", "当地特色餐厅", "商业区"]
_INTEREST_TO_TYPE = {"购物": "shopping", "美食": "food", "人文": "culture", "自然": "nature", "摄影": "photography"}


def _hhmm_to_minutes(hhmm: str) -> int:
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 0


class RuleValidator:
    """Hard-constraint checks over a generated itinerary."""

    def validate(
        self, itinerary: Itinerary, requirement: TravelRequirement, research: Optional[ResearchResult] = None,
    ) -> List[str]:
        issues: List[str] = []
        daily_count_target = requirement.daily_attraction_count or 3
        latest_return = _hhmm_to_minutes(requirement.latest_return_time or "21:30")
        seen_locations: Dict[str, int] = {}
        known_names = self._known_names(research)

        for day in itinerary.days:
            prev_end: Optional[int] = None
            attraction_count = 0
            regions_seen: Set[str] = set()
            for item in day.items:
                start = _hhmm_to_minutes(item.time)
                end = start + item.duration_minutes
                if prev_end is not None and start < prev_end - 5:
                    issues.append(f"第{day.day_number}天 {item.activity}({item.time}) 与前一活动时间冲突")
                prev_end = end

                if item.activity == "attraction":
                    attraction_count += 1
                    key = item.location
                    seen_locations[key] = seen_locations.get(key, 0) + 1

                if item.region:
                    regions_seen.add(item.region)

                if item.activity in ("attraction", "lunch", "dinner") and known_names is not None:
                    name = item.location.split(" (")[0]
                    is_generic = any(marker in item.location for marker in _GENERIC_LOCATION_MARKERS)
                    if not is_generic and name not in known_names:
                        issues.append(f"第{day.day_number}天 内容与实际检索到的数据不符：{name}")

            if len(regions_seen) > 1:
                issues.append(f"第{day.day_number}天 跨区域安排（{'/'.join(sorted(regions_seen))}），请注意交通/换酒店/船票等时间成本")

            if attraction_count > daily_count_target + 1:
                issues.append(f"第{day.day_number}天 景点数量({attraction_count})超出用户期望({daily_count_target})")

            non_return_items = [i for i in day.items if i.activity != "return_to_hotel"]
            if non_return_items:
                last = non_return_items[-1]
                last_end = _hhmm_to_minutes(last.time) + last.duration_minutes
                if last_end > latest_return + 30:
                    issues.append(f"第{day.day_number}天 行程结束时间({last.time}后)超过用户设定的最晚返回酒店时间")

        for loc, count in seen_locations.items():
            if count > 1:
                issues.append(f"景点「{loc}」在行程中重复出现 {count} 次")

        if requirement.budget:
            total_cost = itinerary.total_cost()
            if total_cost > requirement.budget * 1.05:
                over_pct = (total_cost / requirement.budget - 1) * 100
                issues.append(f"预估总花费 {total_cost:.0f} {requirement.budget_currency} 超出预算 {over_pct:.0f}%")

        return issues

    @staticmethod
    def _known_names(research: Optional[ResearchResult]) -> Optional[Set[str]]:
        """Names traceable to real research data, or `None` to skip the check
        entirely (e.g. when called standalone without a `ResearchResult`)."""
        if research is None:
            return None
        names = {e.name for e in research.experiences}
        names.update(h.name for h in research.hotels)
        return names


class LLMReviewer:
    """Soft-dimension scoring: preference match, richness, fatigue, general vibe."""

    def __init__(self) -> None:
        # tier="fast": scores DimensionScores via with_structured_output, which
        # deepseek-reasoner (the "deep" tier) cannot do (no tool-calling support).
        self._llm = get_llm(role="reviewer", tier="fast")
        self._system_prompt = load_prompt("reviewer_agent")

    def review(
        self, itinerary: Itinerary, requirement: TravelRequirement, research: ResearchResult, rule_issues: List[str]
    ) -> DimensionScores:
        if self._llm is not None:
            scores = self._review_with_llm(itinerary, requirement, rule_issues)
            if scores is not None:
                return scores
        return self._review_heuristic(itinerary, requirement, research, rule_issues)

    def _review_with_llm(self, itinerary: Itinerary, requirement: TravelRequirement, rule_issues: List[str]) -> Optional[DimensionScores]:
        try:
            # method="function_calling": see requirement_agent.py's identical
            # comment -- DeepSeek rejects the response_format=json_schema
            # default for pydantic targets.
            structured_llm = self._llm.with_structured_output(DimensionScores, method="function_calling")
            prompt = (
                "请根据以下行程和用户需求，从五个维度打分(0-100)："
                "time_feasibility(时间可行性), route_efficiency(路线效率), preference_match(偏好匹配度), "
                "richness(丰富度), budget(预算符合度)。\n\n"
                f"用户需求: {requirement.model_dump_json()}\n\n"
                f"行程: {itinerary.model_dump_json()}\n\n"
                f"规则检测已发现的问题: {rule_issues}\n"
            )
            messages = []
            if self._system_prompt:
                messages.append(("system", self._system_prompt))
            messages.append(("human", prompt))
            result = structured_llm.invoke(messages)
            if isinstance(result, DimensionScores):
                return result
        except Exception:
            return None
        return None

    def _review_heuristic(
        self, itinerary: Itinerary, requirement: TravelRequirement, research: ResearchResult, rule_issues: List[str]
    ) -> DimensionScores:
        type_by_name = {e.name: e.type for e in research.experiences}
        preference_tags = set(requirement.experience_preferences or [])
        preference_tags.update(_INTEREST_TO_TYPE[i] for i in (requirement.interests or []) if i in _INTEREST_TO_TYPE)

        attraction_items = [i for d in itinerary.days for i in d.items if i.activity == "attraction"]
        matched = 0
        categories_seen = set()
        for item in attraction_items:
            name = item.location.split(" (")[0]
            etype = type_by_name.get(name)
            if etype:
                categories_seen.add(etype)
            if etype and etype in preference_tags:
                matched += 1
            elif etype in ("landmark", "local_life"):
                matched += 0.5

        preference_match = int(min(100, 50 + (matched / max(len(attraction_items), 1)) * 50))
        richness = int(min(100, 40 + len(categories_seen) * 15 + len(attraction_items) * 3))

        time_issues = [i for i in rule_issues if "冲突" in i or "超过" in i]
        route_issues = [i for i in rule_issues if "路程" in i or "路线" in i]
        time_feasibility = max(30, 100 - len(time_issues) * 20)
        route_efficiency = max(40, 100 - len(route_issues) * 15 - len([i for i in rule_issues if "重复" in i]) * 10)

        budget_issues = [i for i in rule_issues if "预算" in i]
        if budget_issues:
            budget_score = max(20, 100 - len(budget_issues) * 30)
        else:
            budget_score = 95

        return DimensionScores(
            time_feasibility=time_feasibility,
            route_efficiency=route_efficiency,
            preference_match=preference_match,
            richness=richness,
            budget=budget_score,
        )


class ReviewerAgent:
    """Combines RuleValidator + LLMReviewer into a single ReviewReport."""

    def __init__(self) -> None:
        self.validator = RuleValidator()
        self.llm_reviewer = LLMReviewer()
        self.settings = get_settings()

    def review(
        self,
        itinerary: Itinerary,
        requirement: TravelRequirement,
        research: ResearchResult,
        loop_count: int,
        rule_issues: Optional[List[str]] = None,
    ) -> ReviewReport:
        if rule_issues is None:
            rule_issues = self.validator.validate(itinerary, requirement, research)
        dimension_scores = self.llm_reviewer.review(itinerary, requirement, research, rule_issues)

        overall = round(
            (
                dimension_scores.time_feasibility
                + dimension_scores.route_efficiency
                + dimension_scores.preference_match
                + dimension_scores.richness
                + dimension_scores.budget
            )
            / 5
        )
        # Hard rule issues cap the score so a plan with real conflicts can't pass.
        if rule_issues:
            overall = min(overall, 84)

        passed = overall >= self.settings.review_pass_score

        revision_instruction: List[str] = []
        if not passed:
            if dimension_scores.budget < 80 or any("预算" in i for i in rule_issues):
                revision_instruction.append("超预算，请优先选择更经济的餐厅/景点，降低总花费。")
            if dimension_scores.time_feasibility < 80 or any("冲突" in i or "超过" in i for i in rule_issues):
                revision_instruction.append("存在时间冲突或超过最晚返回时间，请减少景点数量并放宽时间安排，避免过于疲劳。")
            if dimension_scores.route_efficiency < 80:
                revision_instruction.append("路线效率不高，请按地理位置就近安排行程顺序。")
            if dimension_scores.preference_match < 80:
                revision_instruction.append("与用户兴趣偏好匹配度不足，请增加符合用户偏好类别的项目。")
            if dimension_scores.richness < 80:
                revision_instruction.append("行程丰富度不足，请增加特色体验，避免重复类型的安排。")
            if not revision_instruction:
                revision_instruction.append("请综合优化行程细节以提升整体体验。")

        return ReviewReport(
            score=overall,
            passed=passed,
            dimension_scores=dimension_scores,
            issues=rule_issues,
            revision_instruction=revision_instruction,
            loop_count=loop_count,
        )
