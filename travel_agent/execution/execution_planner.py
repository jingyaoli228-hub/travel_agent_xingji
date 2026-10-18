"""`ExecutionPlanner` (design doc section 13): turns a fused `IntentResult`
into a concrete, ordered `ExecutionPlan` across the four existing agents.
Ordinary service, not a fifth agent -- it only ever names
RequirementAgent/ResearchOrchestrator/PlannerAgent/PresentationAgent.
"""

from __future__ import annotations

from travel_agent.execution.schemas import ExecutionPlan, ExecutionStep
from travel_agent.intent.schemas import IntentContext, IntentResult

_ACTION_BY_AGENT = {
    "RequirementAgent": "APPLY_STATE_PATCH",
    "ResearchOrchestrator": "SEARCH_MORE_ACTIVITIES",
    "PresentationAgent": "PRESENT_PLAN_DIFF",
}


def _planner_action(intent: IntentResult) -> str:
    if intent.target in ("DAY_PLAN", "REGION") or (intent.entities.day_index and intent.entities.preserve_other_days):
        return "REPLAN_PARTIAL_DAY"
    if intent.target == "FULL_ITINERARY":
        return "REPLAN_FULL_TRIP"
    return "APPLY_ACTIVITY_CHANGE"


class ExecutionPlanner:
    def plan(self, intent: IntentResult, context: IntentContext) -> ExecutionPlan:
        steps = []
        for i, agent in enumerate(intent.next_agents, start=1):
            action = _planner_action(intent) if agent == "PlannerAgent" else _ACTION_BY_AGENT.get(agent, "RUN")
            steps.append(
                ExecutionStep(
                    step=i,
                    agent=agent,  # type: ignore[arg-type]
                    action=action,
                    input_ref={"intent_primary": intent.primary_intent},
                )
            )

        preserve_scope = {
            "day_index": intent.entities.day_index,
            "time_period": intent.entities.time_period,
            "preserve_other_days": intent.entities.preserve_other_days,
            "preserve_other_time_periods": intent.entities.preserve_other_time_periods,
            "source_region": intent.entities.source_region,
            "target_region": intent.entities.target_region,
        }

        return ExecutionPlan(trace_id=context.trace_id, steps=steps, preserve_scope=preserve_scope)
