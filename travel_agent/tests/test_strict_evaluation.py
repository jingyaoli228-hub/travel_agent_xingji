"""Offline tests for Round-6 Phase 6: the strict, 8-dimension, hard-penalty
travel evaluation system (`travel_agent/evaluation/{schemas,config,
penalty_rules,llm_judge,revision_router,report_generator}.py`).
"""

from __future__ import annotations

import pytest

from travel_agent.evaluation.config import load_evaluation_config
from travel_agent.evaluation.llm_judge import StrictTravelEvaluator
from travel_agent.evaluation.penalty_rules import detect_penalties
from travel_agent.evaluation.report_generator import generate_notes, generate_report
from travel_agent.evaluation.revision_router import decide_route, presentation_route
from travel_agent.evaluation.schemas import StrictDimensionScores, StrictEvaluationInput, TravelEvaluationResult


def _dims(**overrides) -> StrictDimensionScores:
    base = dict(
        requirement_adherence=15, user_profile_alignment=10, destination_specificity=10,
        activity_richness=10, activity_diversity=7, itinerary_feasibility=12,
        evidence_and_accuracy=4, presentation_quality=4,
    )
    base.update(overrides)
    return StrictDimensionScores(**base)


def _good_itinerary() -> dict:
    return {
        "days": [
            {
                "day_number": 1,
                "items": [
                    {"time": "09:00", "activity": "浅草寺", "location": "浅草", "duration_minutes": 90, "reason": "东京地标，晨间人少适合游览", "estimated_cost": 0},
                    {"time": "12:00", "activity": "一兰拉面", "location": "涩谷", "duration_minutes": 60, "reason": "人气拉面店，性价比高", "estimated_cost": 80},
                    {"time": "15:00", "activity": "上野公园", "location": "上野", "duration_minutes": 90, "reason": "自然风光，适合散步", "estimated_cost": 0},
                ],
            },
            {
                "day_number": 2,
                "items": [
                    {"time": "10:00", "activity": "秋叶原电器街", "location": "秋叶原", "duration_minutes": 120, "reason": "购物与动漫文化体验", "estimated_cost": 200},
                    {"time": "13:00", "activity": "筑地场外市场", "location": "筑地", "duration_minutes": 90, "reason": "新鲜海鲜丼，本地美食体验", "estimated_cost": 150},
                ],
            },
        ]
    }


def _base_input(**overrides) -> StrictEvaluationInput:
    base = dict(
        user_request="东京5天2人游，预算1万",
        travel_requirement={"destination": "东京", "duration_days": 2, "daily_attraction_count": 3},
        final_itinerary=_good_itinerary(),
        tool_evidence=[{"source": "google_places"}],
    )
    base.update(overrides)
    return StrictEvaluationInput(**base)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

def test_load_evaluation_config_has_strict_defaults() -> None:
    config = load_evaluation_config()
    assert config.strict_weights.requirement_adherence == 20
    total = sum(config.strict_weights.model_dump().values())
    assert total == pytest.approx(100)
    assert config.hard_penalties.wrong_destination == -30
    assert config.max_revision_rounds == 2
    assert config.pass_threshold == 80
    assert config.notes_threshold == 65


# ---------------------------------------------------------------------------
# penalty_rules
# ---------------------------------------------------------------------------

def test_detect_empty_day_penalty() -> None:
    itinerary = {"days": [{"day_number": 1, "items": []}, {"day_number": 2, "items": [{"time": "09:00", "activity": "x", "location": "y", "duration_minutes": 60, "reason": "test reason"}]}]}
    result = detect_penalties(_base_input(final_itinerary=itinerary))
    rules = {p.rule for p in result}
    assert "empty_day" in rules


def test_detect_repeated_rejected_activity() -> None:
    episodes = [{"user_id": "u1", "session_id": "s1", "destination": "东京", "rejected_experiences": ["浅草寺"]}]
    result = detect_penalties(_base_input(episodic_memories=episodes))
    rules = {p.rule for p in result}
    assert "repeated_rejected_activity" in rules


def test_detect_missing_activity_description() -> None:
    itinerary = {"days": [{"day_number": 1, "items": [{"time": "09:00", "activity": "x", "location": "y", "duration_minutes": 60, "reason": "ok"}]}]}
    result = detect_penalties(_base_input(final_itinerary=itinerary))
    rules = {p.rule for p in result}
    assert "missing_activity_description" in rules


def test_detect_generic_destination_plan_when_highlights_absent_from_itinerary() -> None:
    result = detect_penalties(
        _base_input(destination_profile={"signature_experiences": ["巴厘舞蹈课", "瑜伽疗愈"]})
    )
    rules = {p.rule for p in result}
    assert "generic_destination_plan" in rules


def test_no_generic_penalty_when_no_destination_profile_given() -> None:
    result = detect_penalties(_base_input())
    rules = {p.rule for p in result}
    assert "generic_destination_plan" not in rules


def test_detect_missed_explicit_activity() -> None:
    result = detect_penalties(_base_input(user_request="东京5天，我想要瑜伽体验"))
    rules = {p.rule for p in result}
    assert "missed_explicit_activity" in rules


def test_detect_schedule_overlap() -> None:
    itinerary = {
        "days": [
            {
                "day_number": 1,
                "items": [
                    {"time": "09:00", "activity": "a", "location": "x", "duration_minutes": 180, "reason": "test reason a"},
                    {"time": "10:00", "activity": "b", "location": "y", "duration_minutes": 60, "reason": "test reason b"},
                ],
            }
        ]
    }
    result = detect_penalties(_base_input(final_itinerary=itinerary))
    rules = {p.rule for p in result}
    assert "geographically_impossible" in rules


def test_good_itinerary_triggers_no_penalties() -> None:
    assert detect_penalties(_base_input()) == []


# ---------------------------------------------------------------------------
# StrictTravelEvaluator (heuristic path)
# ---------------------------------------------------------------------------

def test_heuristic_evaluate_scores_good_itinerary_reasonably_high() -> None:
    result = StrictTravelEvaluator().evaluate(_base_input())
    assert result.overall_score >= 60
    assert result.hard_penalties == []
    assert result.critical_failures == []


def test_heuristic_evaluate_flags_empty_day_as_critical() -> None:
    itinerary = {"days": [{"day_number": 1, "items": []}]}
    result = StrictTravelEvaluator().evaluate(_base_input(final_itinerary=itinerary, travel_requirement={"destination": "东京", "duration_days": 1}))
    assert result.overall_score < 60
    assert result.should_replan is True
    assert any(p.rule == "empty_day" for p in result.hard_penalties)


def test_heuristic_evaluate_no_profile_data_uses_neutral_score_not_zero() -> None:
    result = StrictTravelEvaluator().evaluate(_base_input(user_profile={}))
    assert result.dimension_scores.user_profile_alignment == pytest.approx(10.0)


def test_heuristic_evaluate_profile_alignment_rewards_matching_content() -> None:
    itinerary = {
        "days": [{"day_number": 1, "items": [
            {"time": "09:00", "activity": "瑜伽课", "location": "乌布", "duration_minutes": 90, "reason": "悠闲慢节奏体验，符合用户偏好"},
        ]}]
    }
    result = StrictTravelEvaluator().evaluate(
        _base_input(final_itinerary=itinerary, user_profile={"travel_style": "悠闲慢节奏"},
                     travel_requirement={"destination": "巴厘岛", "duration_days": 1, "daily_attraction_count": 1})
    )
    assert result.dimension_scores.user_profile_alignment > 10.0


def test_heuristic_evaluate_richness_issue_flagged_when_activities_sparse() -> None:
    itinerary = {"days": [{"day_number": 1, "items": [{"time": "09:00", "activity": "x", "location": "y", "duration_minutes": 60, "reason": "仅有的一个活动"}]}] * 1}
    result = StrictTravelEvaluator().evaluate(
        _base_input(final_itinerary=itinerary, travel_requirement={"destination": "东京", "duration_days": 1, "daily_attraction_count": 5})
    )
    assert result.should_research_more is True
    assert result.richness_issues


def test_heuristic_evaluate_never_raises_on_empty_itinerary() -> None:
    result = StrictTravelEvaluator().evaluate(_base_input(final_itinerary={}))
    assert 0 <= result.overall_score <= 100


# ---------------------------------------------------------------------------
# StrictTravelEvaluator (LLM path)
# ---------------------------------------------------------------------------

class _FakeStructuredLLM:
    def __init__(self, result: TravelEvaluationResult) -> None:
        self._result = result

    def invoke(self, messages) -> TravelEvaluationResult:
        return self._result


class _FakeLLM:
    def __init__(self, result: TravelEvaluationResult) -> None:
        self._result = result

    def with_structured_output(self, schema: type, method: str = "function_calling") -> _FakeStructuredLLM:
        return _FakeStructuredLLM(self._result)


def test_llm_path_used_and_merges_heuristic_penalties_not_already_present() -> None:
    fake_result = TravelEvaluationResult(overall_score=90.0, dimension_scores=_dims())
    itinerary = {"days": [{"day_number": 1, "items": []}]}  # would trigger empty_day heuristically
    llm = _FakeLLM(fake_result)

    result = StrictTravelEvaluator().evaluate(
        _base_input(final_itinerary=itinerary, travel_requirement={"destination": "东京", "duration_days": 1}), llm=llm
    )
    assert any(p.rule == "empty_day" for p in result.hard_penalties)
    assert result.overall_score < 90.0  # penalty applied on top of the LLM's own score


def test_llm_path_failure_falls_back_to_heuristic() -> None:
    class _RaisingLLM:
        def with_structured_output(self, schema, method="function_calling"):
            raise RuntimeError("simulated outage")

    result = StrictTravelEvaluator().evaluate(_base_input(), llm=_RaisingLLM())
    assert result.overall_score >= 60  # heuristic path for the "good" fixture itinerary


# ---------------------------------------------------------------------------
# revision_router
# ---------------------------------------------------------------------------

def test_decide_route_high_score_goes_to_final_output() -> None:
    result = TravelEvaluationResult(overall_score=85, dimension_scores=_dims())
    assert decide_route(result, revision_round=0) == "final_output"


def test_decide_route_low_score_within_budget_goes_to_planner() -> None:
    result = TravelEvaluationResult(overall_score=40, dimension_scores=_dims())
    assert decide_route(result, revision_round=0) == "planner"


def test_decide_route_low_score_at_max_rounds_forces_final_output() -> None:
    result = TravelEvaluationResult(overall_score=40, dimension_scores=_dims())
    assert decide_route(result, revision_round=2) == "final_output"


def test_decide_route_critical_failure_forces_planner_even_at_notes_score() -> None:
    result = TravelEvaluationResult(overall_score=70, dimension_scores=_dims(), critical_failures=["严重问题"])
    assert decide_route(result, revision_round=0) == "planner"


def test_presentation_route_pass_vs_notes() -> None:
    high = TravelEvaluationResult(overall_score=85, dimension_scores=_dims())
    mid = TravelEvaluationResult(overall_score=70, dimension_scores=_dims())
    assert presentation_route(high) == "final_output"
    assert presentation_route(mid) == "final_output_with_notes"


# ---------------------------------------------------------------------------
# report_generator
# ---------------------------------------------------------------------------

def test_generate_report_includes_dimension_scores_and_penalties() -> None:
    result = TravelEvaluationResult(
        overall_score=55, dimension_scores=_dims(),
        hard_penalties=[{"rule": "empty_day", "points": -10, "reason": "第1天没有安排"}],
        improvement_actions=["补充候选活动"],
    )
    report = generate_report(result, trace_id="trace-123")
    assert "trace-123" in report
    assert "55" in report
    assert "empty_day" in report
    assert "补充候选活动" in report


def test_generate_notes_is_short_and_score_prefixed() -> None:
    result = TravelEvaluationResult(overall_score=70, dimension_scores=_dims(), improvement_actions=["增加活动多样性"])
    notes = generate_notes(result)
    assert "70" in notes
    assert "增加活动多样性" in notes
