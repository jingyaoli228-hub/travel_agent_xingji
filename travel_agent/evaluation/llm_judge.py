"""`StrictTravelEvaluator` (requirement doc sections 22-27): the graph-wired,
8-dimension, hard-penalty evaluation of a *finished itinerary in full
context* -- separate from `judge.py`'s `LLMJudge` (see that module's
docstring for why the two don't merge).

Dual-path, same convention as every other module in this codebase
(`ReviewerAgent`, `DestinationIntelligenceService`, `LLMJudge` itself): LLM
structured-output scoring when a client is given, a heuristic fallback
otherwise so the evaluator "never returns nothing". The heuristic path is
deliberately not a pushover -- hard penalties (`penalty_rules.py`) always
apply on top of it -- but it also can't reason about genuinely subjective
calls (does this itinerary *feel* generic?) the way an LLM can; where the
heuristic has no reliable signal, it returns a documented neutral default
rather than guessing.
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field

from travel_agent.evaluation.config import load_evaluation_config
from travel_agent.evaluation.penalty_rules import detect_penalties
from travel_agent.evaluation.schemas import StrictDimensionScores, StrictEvaluationInput, TravelEvaluationResult
from travel_agent.rag.topic_vocab import TOPIC_KEYWORDS
from travel_agent.utils.logging import get_logger

_logger = get_logger("travel_agent.evaluation.llm_judge")

_NEUTRAL_PROFILE_SCORE = 10.0  # out of 15 -- "no profile data to judge against" is not the plan's fault
_NEUTRAL_DESTINATION_SCORE = 8.0  # out of 15 -- same reasoning, no destination_profile to compare against


def _items(evaluation_input: StrictEvaluationInput) -> List[dict]:
    days = evaluation_input.final_itinerary.get("days") or []
    return [item for day in days for item in (day.get("items") or [])]


def _itinerary_text(evaluation_input: StrictEvaluationInput) -> str:
    parts = []
    for item in _items(evaluation_input):
        parts.append(str(item.get("activity") or ""))
        parts.append(str(item.get("location") or ""))
        parts.append(str(item.get("reason") or ""))
    return " ".join(parts)


def _score_requirement_adherence(evaluation_input: StrictEvaluationInput) -> float:
    req = evaluation_input.travel_requirement
    days = evaluation_input.final_itinerary.get("days") or []
    score = 0.0
    if req.get("destination"):
        score += 5.0
    duration_days = req.get("duration_days")
    if not duration_days or len(days) == duration_days:
        score += 5.0
    if days and all(day.get("items") for day in days):
        score += 5.0
    daily_target = req.get("daily_attraction_count")
    if daily_target and days:
        avg_items = sum(len(day.get("items") or []) for day in days) / len(days)
        closeness = 1 - min(abs(avg_items - daily_target) / max(daily_target, 1), 1)
        score += 5.0 * closeness
    elif days:
        score += 5.0
    return round(min(score, 20.0), 1)


def _score_user_profile_alignment(evaluation_input: StrictEvaluationInput) -> float:
    profile = evaluation_input.user_profile
    if not profile:
        return _NEUTRAL_PROFILE_SCORE
    values: List[str] = []
    for value in profile.values():
        values.extend(str(v) for v in value) if isinstance(value, list) else values.append(str(value))
    if not values:
        return _NEUTRAL_PROFILE_SCORE
    text = _itinerary_text(evaluation_input)
    matched = sum(1 for v in values if v and v in text)
    ratio = matched / len(values)
    return round(min(5.0 + ratio * 10.0, 15.0), 1)


def _score_destination_specificity(evaluation_input: StrictEvaluationInput) -> float:
    profile = evaluation_input.destination_profile
    highlights = list(profile.get("signature_experiences") or []) + list(profile.get("highlights") or [])
    if not highlights:
        return _NEUTRAL_DESTINATION_SCORE
    text = _itinerary_text(evaluation_input)
    matched = sum(1 for h in highlights if str(h) and str(h) in text)
    ratio = matched / len(highlights)
    return round(min(3.0 + ratio * 12.0, 15.0), 1)


def _score_activity_richness(evaluation_input: StrictEvaluationInput) -> float:
    days = evaluation_input.final_itinerary.get("days") or []
    if not days:
        return 0.0
    req = evaluation_input.travel_requirement
    expected_per_day = req.get("daily_attraction_count") or 3
    total_items = sum(len(day.get("items") or []) for day in days)
    expected_total = max(expected_per_day * len(days), 1)
    ratio = min(total_items / expected_total, 1.5)  # a bit of headroom above target isn't penalized
    return round(min(ratio, 1.0) * 15.0, 1)


_CATEGORY_KEYWORDS = {**TOPIC_KEYWORDS, "早餐": "美食", "午餐": "美食", "晚餐": "美食", "breakfast": "美食", "lunch": "美食", "dinner": "美食"}


def _infer_category(item: dict) -> str:
    text = f"{item.get('activity', '')} {item.get('location', '')}"
    for keyword, category in _CATEGORY_KEYWORDS.items():
        if keyword in text:
            return category
    return str(item.get("activity") or "other")


def _score_activity_diversity(evaluation_input: StrictEvaluationInput) -> float:
    items = _items(evaluation_input)
    if len(items) < 2:
        return 10.0 if items else 0.0
    categories = [_infer_category(item) for item in items]
    unique_ratio = len(set(categories)) / len(categories)
    max_run = 1
    current_run = 1
    for prev, cur in zip(categories, categories[1:]):
        current_run = current_run + 1 if cur == prev else 1
        max_run = max(max_run, current_run)
    run_penalty = 0.3 if max_run >= 3 else 0.0
    return round(max(unique_ratio - run_penalty, 0.0) * 10.0, 1)


def _score_itinerary_feasibility(evaluation_input: StrictEvaluationInput, overlap_hits: int) -> float:
    days = evaluation_input.final_itinerary.get("days") or []
    if not days:
        return 0.0
    empty_days = sum(1 for day in days if not day.get("items"))
    score = 15.0
    score -= empty_days * 5.0
    score -= overlap_hits * 4.0
    return round(max(score, 0.0), 1)


def _score_evidence_and_accuracy(evaluation_input: StrictEvaluationInput) -> float:
    return 5.0 if evaluation_input.tool_evidence else 2.5


def _score_presentation_quality(evaluation_input: StrictEvaluationInput) -> float:
    items = _items(evaluation_input)
    if not items:
        return 0.0
    described = sum(1 for item in items if len(str(item.get("reason") or "").strip()) >= 4)
    return round((described / len(items)) * 5.0, 1)


class StrictTravelEvaluator:
    def evaluate(self, evaluation_input: StrictEvaluationInput, llm: Optional[Any] = None) -> TravelEvaluationResult:
        if llm is not None:
            result = self._evaluate_with_llm(evaluation_input, llm)
            if result is not None:
                return result
        return self._evaluate_heuristic(evaluation_input)

    def _evaluate_heuristic(self, evaluation_input: StrictEvaluationInput) -> TravelEvaluationResult:
        hard_penalties = detect_penalties(evaluation_input)
        overlap_hits = sum(1 for p in hard_penalties if p.rule == "geographically_impossible")

        dims = StrictDimensionScores(
            requirement_adherence=_score_requirement_adherence(evaluation_input),
            user_profile_alignment=_score_user_profile_alignment(evaluation_input),
            destination_specificity=_score_destination_specificity(evaluation_input),
            activity_richness=_score_activity_richness(evaluation_input),
            activity_diversity=_score_activity_diversity(evaluation_input),
            itinerary_feasibility=_score_itinerary_feasibility(evaluation_input, overlap_hits),
            evidence_and_accuracy=_score_evidence_and_accuracy(evaluation_input),
            presentation_quality=_score_presentation_quality(evaluation_input),
        )

        base_score = sum(dims.model_dump().values())
        penalty_total = sum(p.points for p in hard_penalties)
        overall = round(max(min(base_score + penalty_total, 100.0), 0.0), 1)

        richness_issues = ["活动数量不足以支撑行程天数"] if dims.activity_richness < 8 else []
        diversity_issues = ["活动类型过于单一，缺少多样性"] if dims.activity_diversity < 5 else []
        feasibility_issues = [p.reason for p in hard_penalties if p.rule in ("empty_day", "geographically_impossible")]
        missing_prefs = [p.reason for p in hard_penalties if p.rule == "missed_explicit_activity"]
        repeated_rejected = [p.reason for p in hard_penalties if p.rule == "repeated_rejected_activity"]

        critical_failures = [p.reason for p in hard_penalties if p.points <= -20]

        improvement_actions = []
        if richness_issues:
            improvement_actions.append("增加更多符合天数和每日安排数量的候选活动")
        if diversity_issues:
            improvement_actions.append("替换连续同类型活动，增加多样性")
        if missing_prefs:
            improvement_actions.append("补充用户明确要求但缺失的活动")
        if repeated_rejected:
            improvement_actions.append("移除用户历史上明确拒绝过的内容")
        if feasibility_issues:
            improvement_actions.append("调整行程时间安排，解决时间冲突或空白天")

        return TravelEvaluationResult(
            overall_score=overall,
            dimension_scores=dims,
            hard_penalties=hard_penalties,
            missing_user_preferences=missing_prefs,
            repeated_rejected_preferences=repeated_rejected,
            richness_issues=richness_issues,
            diversity_issues=diversity_issues,
            feasibility_issues=feasibility_issues,
            critical_failures=critical_failures,
            improvement_actions=improvement_actions,
            should_research_more=bool(richness_issues or diversity_issues or missing_prefs),
            should_replan=bool(feasibility_issues),
            suggested_research_directions=missing_prefs,
        )

    def _evaluate_with_llm(self, evaluation_input: StrictEvaluationInput, llm: Any) -> Optional[TravelEvaluationResult]:
        try:
            structured_llm = llm.with_structured_output(TravelEvaluationResult, method="function_calling")
            prompt = (
                "你是旅行规划系统的严格评测员。请基于以下完整上下文，对最终行程按 8 个维度打分并给出扣分原因，"
                "不要因为格式完整就给高分：\n"
                "requirement_adherence(0-20，是否满足目的地/日期/预算/人数/节奏/活动偏好/是否遵守"
                "\"其他不变\"等硬约束)、user_profile_alignment(0-15，是否符合用户长期画像、是否重复推荐"
                "已拒绝内容)、destination_specificity(0-15，是否体现目的地特色而非通用模板)、"
                "activity_richness(0-15，活动数量和信息是否足够支撑天数)、activity_diversity(0-10，"
                "类型是否多样，不能连续同类型)、itinerary_feasibility(0-15，时间路线是否可行)、"
                "evidence_and_accuracy(0-5，强时效信息是否有真实来源支持)、presentation_quality(0-5，"
                "介绍是否完整清晰)。\n"
                "同时给出 hard_penalties(触发的硬性扣分项及原因)、"
                "passed_requirements/failed_requirements、missing_user_preferences、"
                "repeated_rejected_preferences、richness_issues/diversity_issues/feasibility_issues/"
                "evidence_issues、critical_failures、improvement_actions、"
                "should_research_more/should_replan/suggested_research_directions。\n\n"
                f"用户原始请求: {evaluation_input.user_request}\n"
                f"本轮反馈: {evaluation_input.user_feedback}\n"
                f"结构化旅行需求: {evaluation_input.travel_requirement}\n"
                f"用户画像: {evaluation_input.user_profile}\n"
                f"相关情景记忆: {evaluation_input.episodic_memories}\n"
                f"目的地画像: {evaluation_input.destination_profile}\n"
                f"候选活动: {evaluation_input.candidate_activities}\n"
                f"最终行程: {evaluation_input.final_itinerary}\n"
                f"工具证据: {evaluation_input.tool_evidence}\n"
                f"其他日期/时段是否需保持不变: {evaluation_input.preserve_other_days}\n"
            )
            result = structured_llm.invoke([("human", prompt)])
            if isinstance(result, TravelEvaluationResult):
                # Heuristic hard-penalty detection still runs and is merged in --
                # it catches objectively-checkable violations (schedule overlaps,
                # repeated-rejected content) the LLM might phrase differently or miss,
                # without overriding whatever the LLM itself already found.
                existing_rules = {p.rule for p in result.hard_penalties}
                for hit in detect_penalties(evaluation_input):
                    if hit.rule not in existing_rules:
                        result.hard_penalties.append(hit)
                        result.overall_score = round(max(min(result.overall_score + hit.points, 100.0), 0.0), 1)
                return result
        except Exception as exc:  # noqa: BLE001 -- fall back to heuristic, never raise
            _logger.warning("StrictTravelEvaluator LLM path failed, using heuristic: %s", exc)
        return None
