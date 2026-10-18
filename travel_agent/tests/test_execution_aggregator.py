"""Unit tests for travel_agent/execution/execution_planner.py and
result_aggregator.py. AgentRouter (which depends on PlannerAgent.run_partial,
added alongside the Activity Card work) is exercised end-to-end in
test_post_plan_feedback.py instead of in isolation here.
"""

from __future__ import annotations

from travel_agent.execution.execution_planner import ExecutionPlanner
from travel_agent.execution.result_aggregator import AgentResultAggregator
from travel_agent.execution.schemas import StepResult
from travel_agent.intent.schemas import IntentContext, IntentResult, TravelIntentEntities
from travel_agent.schemas.itinerary import DayPlan, Itinerary, ItineraryItem
from travel_agent.schemas.travel_requirement import TravelRequirement


def _item(time, activity, location, region=None):
    return ItineraryItem(time=time, activity=activity, location=location, duration_minutes=60, estimated_cost=0, reason="", region=region)


def test_execution_planner_orders_steps_and_sets_partial_day_action():
    intent = IntentResult(
        task_type="PLAN_MODIFICATION",
        operation="REPLAN",
        target="DAY_PLAN",
        primary_intent="REPLAN_PARTIAL_DAY",
        entities=TravelIntentEntities(day_index=3, time_period="AFTERNOON", preserve_other_days=True, add_categories=["wellness"]),
        next_agents=["RequirementAgent", "ResearchOrchestrator", "PlannerAgent", "PresentationAgent"],
    )
    ctx = IntentContext(current_message="x", trace_id="abc123")
    plan = ExecutionPlanner().plan(intent, ctx)
    assert [s.agent for s in plan.steps] == ["RequirementAgent", "ResearchOrchestrator", "PlannerAgent", "PresentationAgent"]
    planner_step = next(s for s in plan.steps if s.agent == "PlannerAgent")
    assert planner_step.action == "REPLAN_PARTIAL_DAY"
    assert plan.preserve_scope["day_index"] == 3
    assert plan.trace_id == "abc123"


def test_aggregator_detects_preserved_and_changed_days():
    previous = Itinerary(days=[
        DayPlan(day_number=1, items=[_item("09:00", "attraction", "浅草寺")]),
        DayPlan(day_number=2, items=[_item("09:00", "attraction", "银座")]),
        DayPlan(day_number=3, items=[_item("09:00", "attraction", "上野公园")]),
    ])
    updated = Itinerary(days=[
        DayPlan(day_number=1, items=[_item("09:00", "attraction", "浅草寺")]),
        DayPlan(day_number=2, items=[_item("09:00", "attraction", "银座")]),
        DayPlan(day_number=3, items=[_item("09:00", "attraction", "瑜伽课")]),
    ])
    intent = IntentResult(entities=TravelIntentEntities(day_index=3, preserve_other_days=True))
    result = AgentResultAggregator().aggregate(
        intent=intent,
        step_results=[StepResult(step=1, agent="PlannerAgent", action="REPLAN_PARTIAL_DAY")],
        requirement_before=TravelRequirement(),
        requirement_after=TravelRequirement(),
        previous_itinerary=previous,
        updated_itinerary=updated,
        new_activity_candidates=[{"name": "瑜伽课"}],
        trace_id="t1",
    )
    assert result.preserved_scope["day_numbers"] == [1, 2]
    assert result.changed_scope["day_numbers"] == [3]
    assert result.warnings == []


def test_aggregator_warns_when_unrequested_day_changes():
    previous = Itinerary(days=[
        DayPlan(day_number=1, items=[_item("09:00", "attraction", "浅草寺")]),
        DayPlan(day_number=2, items=[_item("09:00", "attraction", "银座")]),
    ])
    updated = Itinerary(days=[
        DayPlan(day_number=1, items=[_item("09:00", "attraction", "浅草寺变了")]),
        DayPlan(day_number=2, items=[_item("09:00", "attraction", "银座")]),
    ])
    intent = IntentResult(entities=TravelIntentEntities(day_index=2, preserve_other_days=True))
    result = AgentResultAggregator().aggregate(
        intent=intent,
        step_results=[],
        requirement_before=TravelRequirement(),
        requirement_after=TravelRequirement(),
        previous_itinerary=previous,
        updated_itinerary=updated,
        new_activity_candidates=[],
        trace_id="t2",
    )
    assert result.changed_scope["day_numbers"] == [1]
    assert any("第1" in w or "[1]" in w for w in result.warnings)


def test_aggregator_flags_duplicate_locations():
    updated = Itinerary(days=[
        DayPlan(day_number=1, items=[_item("09:00", "attraction", "浅草寺")]),
        DayPlan(day_number=2, items=[_item("09:00", "attraction", "浅草寺")]),
    ])
    intent = IntentResult()
    result = AgentResultAggregator().aggregate(
        intent=intent, step_results=[], requirement_before=TravelRequirement(), requirement_after=TravelRequirement(),
        previous_itinerary=None, updated_itinerary=updated, new_activity_candidates=[], trace_id="t3",
    )
    assert any("重复出现" in w for w in result.warnings)


def test_aggregator_diffs_requirement_changes():
    before = TravelRequirement(experience_preferences=["landmark"])
    after = TravelRequirement(experience_preferences=["landmark", "wellness"])
    result = AgentResultAggregator().aggregate(
        intent=IntentResult(), step_results=[], requirement_before=before, requirement_after=after,
        previous_itinerary=None, updated_itinerary=None, new_activity_candidates=[], trace_id="t4",
    )
    assert "experience_preferences" in result.requirement_changes
