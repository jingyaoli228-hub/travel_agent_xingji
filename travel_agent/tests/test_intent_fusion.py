"""Unit tests for travel_agent/intent/fusion_resolver.py and the end-to-end
MultiSignalIntentInterpreter (Fast Path + Deep Path)."""

from __future__ import annotations

from travel_agent.intent.fusion_resolver import FusionResolver, build_fast_result, requires_replanning
from travel_agent.intent.interpreter import MultiSignalIntentInterpreter
from travel_agent.intent.pattern_parser import PatternParser
from travel_agent.intent.schemas import (
    EmbeddingIntentResult,
    FeedbackCandidate,
    IntentCandidate,
    IntentContext,
    IntentResult,
    TravelIntentEntities,
)

UBUD_MESSAGE = "第三天下午再增加两个乌布附近的瑜伽课，其他安排不要动。"


def _post_plan_ctx(**overrides) -> IntentContext:
    base = dict(
        current_message=UBUD_MESSAGE,
        current_phase="post_plan_feedback",
        current_plan_summary={"day_count": 5},
        current_regions=["乌布", "Canggu"],
    )
    base.update(overrides)
    return IntentContext(**base)


def test_build_fast_result_none_for_ambiguous_message():
    pattern = PatternParser().parse("第三个不要了，换成类似第二个但更小众的", _post_plan_ctx())
    assert build_fast_result(pattern, _post_plan_ctx()) is None


def test_build_fast_result_confirms_with_valid_context():
    ctx = _post_plan_ctx(current_message="确认")
    pattern = PatternParser().parse("确认", ctx)
    result = build_fast_result(pattern, ctx)
    assert result is not None
    assert result.primary_intent == "CONFIRM_ITINERARY"
    assert result.confidence >= 0.9


def test_build_fast_result_none_when_day_does_not_exist():
    ctx = _post_plan_ctx(current_plan_summary={"day_count": 2})
    message = "第三天下午增加一个咖啡店"
    pattern = PatternParser().parse(message, ctx)
    assert build_fast_result(pattern, ctx) is None


def test_build_fast_result_add_activity_with_valid_day():
    ctx = _post_plan_ctx(current_plan_summary={"day_count": 5})
    message = "第三天下午增加一个咖啡店"
    pattern = PatternParser().parse(message, ctx)
    result = build_fast_result(pattern, ctx)
    assert result is not None
    assert result.primary_intent == "ADD_ACTIVITY"
    assert result.entities.day_index == 3
    assert "ResearchOrchestrator" in result.next_agents
    assert "PlannerAgent" in result.next_agents
    assert "PresentationAgent" in result.next_agents


def test_fuse_merges_feedback_types_and_categories_into_state_patch():
    ctx = _post_plan_ctx()
    pattern = PatternParser().parse(UBUD_MESSAGE, ctx)
    embedding = EmbeddingIntentResult(
        intent_candidates=[IntentCandidate(intent="ADD_ACTIVITY", score=0.7)],
        feedback_candidates=[FeedbackCandidate(feedback_type="PREFERS_WELLNESS", score=0.5)],
    )
    result = FusionResolver().fuse(UBUD_MESSAGE, ctx, pattern, embedding, None)
    assert "wellness" in result.state_patch.get("preferences_to_add", [])
    assert result.entities.day_index == 3
    assert result.entities.time_period == "AFTERNOON"
    assert result.entities.preserve_other_days is True


def test_fuse_prefers_llm_primary_intent_when_present_and_confident():
    ctx = _post_plan_ctx()
    pattern = PatternParser().parse(UBUD_MESSAGE, ctx)
    embedding = EmbeddingIntentResult(intent_candidates=[IntentCandidate(intent="REPLAN_PARTIAL_DAY", score=0.6)])
    llm_result = IntentResult(
        task_type="PLAN_MODIFICATION",
        operation="REPLAN",
        target="DAY_PLAN",
        primary_intent="REPLAN_PARTIAL_DAY",
        secondary_intents=["ADD_ACTIVITY"],
        feedback_types=["TOO_TRADITIONAL", "PREFERS_WELLNESS"],
        entities=TravelIntentEntities(
            day_index=3, time_period="AFTERNOON", add_categories=["wellness", "nightlife"], preserve_other_days=True,
        ),
        requires_research=True,
        requires_replanning=True,
        confidence=0.95,
        next_agents=["ResearchOrchestrator", "PlannerAgent", "PresentationAgent"],
    )
    result = FusionResolver().fuse(UBUD_MESSAGE, ctx, pattern, embedding, llm_result)
    assert result.primary_intent == "REPLAN_PARTIAL_DAY"
    assert result.confidence >= 0.82
    assert result.interaction_mode == "NORMAL_FLOW"
    assert result.next_agents == llm_result.next_agents
    assert result.entities.preserve_other_days is True


def test_fuse_side_query_preserves_state(monkeypatch):
    ctx = _post_plan_ctx(current_message="东京明天天气怎么样")
    pattern = PatternParser().parse("东京明天天气怎么样", ctx)
    result = FusionResolver().fuse("东京明天天气怎么样", ctx, pattern, EmbeddingIntentResult(), None)
    assert result.interaction_mode == "SIDE_QUERY"
    assert result.preserve_current_state is True
    assert result.resume_phase == "post_plan_feedback"
    assert result.next_agents == []


def test_interpreter_end_to_end_offline_ubud_scenario(no_llm):
    ctx = _post_plan_ctx()
    result = MultiSignalIntentInterpreter().interpret(UBUD_MESSAGE, ctx)
    assert result.entities.day_index == 3
    assert result.entities.preserve_other_days is True
    assert "wellness" in (result.entities.add_categories or []) or "wellness" in result.state_patch.get("preferences_to_add", [])


def test_interpreter_fast_path_confirm_offline(no_llm):
    ctx = _post_plan_ctx(current_message="确认")
    result = MultiSignalIntentInterpreter().interpret("确认", ctx)
    assert result.primary_intent == "CONFIRM_ITINERARY"
    assert result.evidence.get("fusion", {}).get("path") == "fast"


# -- Round-5: requires_replanning() REGION gap (the actual root cause of the
# "region swap never reaches PlannerAgent" misrouting bug -- everything else
# in the pipeline could parse a REGION_REPLACEMENT intent correctly and it
# still wouldn't trigger a replan without this). -----------------------------


def test_requires_replanning_covers_region_target():
    assert requires_replanning("REPLACE", "REGION") is True
    # Existing targets must still work -- this must be additive, not a rewrite.
    assert requires_replanning("REPLACE", "ACTIVITY") is True
    assert requires_replanning("REPLAN", "DAY_PLAN") is True
    assert requires_replanning("QUERY", "REGION") is False


REGION_SWAP_MESSAGE = "把第3天的Ubud换成努沙佩尼达，我想浮潜和滑翔伞"


def _region_swap_ctx(**overrides) -> IntentContext:
    base = dict(
        current_message=REGION_SWAP_MESSAGE,
        current_phase="post_plan_feedback",
        current_plan_summary={"day_count": 5},
        current_regions=["Ubud", "Canggu"],
    )
    base.update(overrides)
    return IntentContext(**base)


def test_fast_result_region_replacement_routes_to_research_and_planner():
    ctx = _region_swap_ctx()
    pattern = PatternParser().parse(REGION_SWAP_MESSAGE, ctx)
    result = build_fast_result(pattern, ctx)
    assert result is not None
    assert result.primary_intent == "REGION_REPLACEMENT"
    assert result.target == "REGION"
    assert result.requires_replanning is True
    assert "ResearchOrchestrator" in result.next_agents
    assert "PlannerAgent" in result.next_agents
    assert result.entities.source_region == "Ubud"
    assert result.entities.target_region == "努沙佩尼达"
