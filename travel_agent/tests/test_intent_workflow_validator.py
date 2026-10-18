"""Unit tests for travel_agent/intent/workflow_validator.py."""

from __future__ import annotations

from travel_agent.intent.schemas import IntentContext, TravelIntentEntities
from travel_agent.intent.workflow_validator import WorkflowStateValidator


def _ctx(**kwargs) -> IntentContext:
    return IntentContext(current_message=kwargs.pop("current_message", ""), **kwargs)


def test_day_reference_invalid_before_itinerary_exists():
    ctx = _ctx(current_phase="selection", current_plan_summary={})
    entities = TravelIntentEntities(day_index=3)
    result = WorkflowStateValidator().validate(entities, "PLAN_MODIFICATION", "REPLAN_PARTIAL_DAY", ctx)
    assert result.is_valid is False
    assert result.referenced_day_exists is False


def test_day_reference_valid_within_range():
    ctx = _ctx(current_phase="post_plan_feedback", current_plan_summary={"day_count": 5})
    entities = TravelIntentEntities(day_index=3)
    result = WorkflowStateValidator().validate(entities, "PLAN_MODIFICATION", "REPLAN_PARTIAL_DAY", ctx)
    assert result.is_valid is True
    assert result.referenced_day_exists is True


def test_day_reference_out_of_range():
    ctx = _ctx(current_phase="post_plan_feedback", current_plan_summary={"day_count": 3})
    entities = TravelIntentEntities(day_index=5)
    result = WorkflowStateValidator().validate(entities, "PLAN_MODIFICATION", "REPLAN_PARTIAL_DAY", ctx)
    assert result.is_valid is False
    assert result.referenced_day_exists is False


def test_side_query_sets_resume_phase():
    ctx = _ctx(current_phase="selection")
    entities = TravelIntentEntities()
    result = WorkflowStateValidator().validate(entities, "INFORMATION_QUERY", "QUERY_WEATHER", ctx)
    assert result.is_side_query is True
    assert result.resume_phase == "selection"


def test_pending_confirmation_flagged_when_unaddressed():
    ctx = _ctx(current_phase="confirmation", pending_confirmation={"question": "确认吗？"})
    entities = TravelIntentEntities()
    result = WorkflowStateValidator().validate(entities, "PLAN_MODIFICATION", "ADD_ACTIVITY", ctx)
    assert any("待确认" in v for v in result.violations)


def test_same_destination_does_not_touch_locked_constraint():
    ctx = _ctx(
        current_phase="post_plan_feedback",
        current_destination="北京",
        immutable_constraints={"destination": "北京", "budget": 6000},
    )
    entities = TravelIntentEntities(destination="北京", add_categories=["人文"])
    result = WorkflowStateValidator().validate(entities, "PLAN_MODIFICATION", "APPLY_REVIEW_FIXES", ctx)
    assert result.touches_locked_constraint is False
    assert not any("覆盖已确认" in violation for violation in result.violations)


def test_different_destination_touches_locked_constraint():
    ctx = _ctx(
        current_phase="post_plan_feedback",
        current_destination="北京",
        immutable_constraints={"destination": "北京", "budget": 6000},
    )
    entities = TravelIntentEntities(destination="上海")
    result = WorkflowStateValidator().validate(entities, "PLAN_MODIFICATION", "REPLAN", ctx)
    assert result.touches_locked_constraint is True
    assert any("覆盖已确认" in violation for violation in result.violations)
