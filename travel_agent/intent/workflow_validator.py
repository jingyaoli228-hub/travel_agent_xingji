"""Workflow-state validator (design doc section 11).

Checks a candidate intent against the *actual* current session state -- not
a text classifier, a hard-constraint layer: does the referenced day/activity
exist, is a locked constraint about to be silently overwritten, and is this
actually just a side query that should leave the main flow (`resume_phase`)
untouched once answered.
"""

from __future__ import annotations

from typing import List, Optional

from travel_agent.intent.config import load_fusion_config
from travel_agent.intent.schemas import IntentContext, TravelIntentEntities, WorkflowValidationResult

# Phases in which no itinerary exists yet -- any day/activity reference is
# necessarily invalid there (see graph/state.py::AgentState.stage).
_PHASES_WITHOUT_ITINERARY = {
    "requirement", "clarification", "region_confirmation", "confirmation", "research", "selection",
}

_CONFIRMATION_INTENTS = {"CONFIRM_REQUIREMENT", "CONFIRM_SELECTION", "CONFIRM_ITINERARY", "REJECT_CURRENT_OPTIONS"}


class WorkflowStateValidator:
    def validate(
        self,
        entities: TravelIntentEntities,
        task_type: str,
        primary_intent: str,
        context: IntentContext,
    ) -> WorkflowValidationResult:
        violations: List[str] = []
        is_valid = True

        is_side_query = task_type == "INFORMATION_QUERY"
        resume_phase = context.current_phase if is_side_query else None

        referenced_day_exists: Optional[bool] = None
        if entities.day_index is not None:
            day_count = (context.current_plan_summary or {}).get("day_count")
            if context.current_phase in _PHASES_WITHOUT_ITINERARY or not day_count:
                referenced_day_exists = False
                violations.append(f"引用了第{entities.day_index}天，但当前尚未生成行程")
                is_valid = False
            else:
                referenced_day_exists = 1 <= entities.day_index <= day_count
                if not referenced_day_exists:
                    violations.append(f"第{entities.day_index}天不存在（行程共{day_count}天）")
                    is_valid = False

        referenced_activity_exists: Optional[bool] = None
        if entities.activity_ids:
            known_ids = set(context.selected_activity_ids) | set(context.visible_candidate_ids)
            referenced_activity_exists = any(a in known_ids for a in entities.activity_ids)
            if not referenced_activity_exists:
                violations.append("引用的活动不在当前可见/已选列表中")

        touches_locked_constraint = False
        if primary_intent != "MODIFY_REQUIREMENT" and entities.destination:
            locked_keys = set((context.immutable_constraints or {}).keys())
            if locked_keys & {"destination", "budget", "start_date", "end_date"}:
                touches_locked_constraint = True
                violations.append("该修改会覆盖已确认的硬约束（目的地/日期/预算），需用户显式确认")

        if (
            context.pending_confirmation
            and not is_side_query
            and primary_intent not in _CONFIRMATION_INTENTS
        ):
            violations.append("存在待确认项，当前请求未直接回应它")

        cfg = load_fusion_config().intent_fusion
        penalty = cfg.workflow_invalid_penalty if not is_valid else 0.0

        return WorkflowValidationResult(
            is_valid=is_valid,
            violations=violations,
            is_side_query=is_side_query,
            resume_phase=resume_phase,
            referenced_day_exists=referenced_day_exists,
            referenced_activity_exists=referenced_activity_exists,
            touches_locked_constraint=touches_locked_constraint,
            penalty=penalty,
        )
