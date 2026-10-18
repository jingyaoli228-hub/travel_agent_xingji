"""`AgentResultAggregator` (design doc section 14): merges the AgentRouter's
partial results into one coherent, diff-aware update -- and, critically,
checks the invariant this whole upgrade exists to guarantee: when the user
said "other days unchanged", did they actually stay unchanged.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from travel_agent.execution.schemas import AggregatedExecutionResult, StepResult
from travel_agent.intent.schemas import IntentResult
from travel_agent.schemas.itinerary import Itinerary
from travel_agent.schemas.travel_requirement import TravelRequirement


def _diff_requirement(before: TravelRequirement, after: TravelRequirement) -> Dict[str, Any]:
    b, a = before.model_dump(), after.model_dump()
    return {k: {"before": b.get(k), "after": v} for k, v in a.items() if v != b.get(k)}


def _diff_itinerary(
    previous: Optional[Itinerary], updated: Optional[Itinerary], intent: IntentResult
) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    warnings: List[str] = []
    preserved_days: List[int] = []
    changed_days: List[int] = []

    if previous is not None and updated is not None:
        prev_by_day = {d.day_number: d for d in previous.days}
        for day in updated.days:
            prev_day = prev_by_day.get(day.day_number)
            # Runtime identity is intentionally different for separately
            # materialized but semantically identical plans; it must not turn
            # an unchanged day into a false positive diff.
            exclude_identity = {"items": {"__all__": {"item_id"}}}
            if prev_day is not None and prev_day.model_dump(exclude=exclude_identity) == day.model_dump(exclude=exclude_identity):
                preserved_days.append(day.day_number)
            else:
                changed_days.append(day.day_number)

        if intent.entities.preserve_other_days and intent.entities.day_index:
            unexpected = [d for d in changed_days if d != intent.entities.day_index]
            if unexpected:
                warnings.append(f"用户要求仅修改第{intent.entities.day_index}天，但检测到第{unexpected}天也发生了变化")

    if updated is not None:
        seen: Dict[str, int] = {}
        for day in updated.days:
            for item in day.items:
                if item.activity == "attraction":
                    seen[item.location] = seen.get(item.location, 0) + 1
        warnings.extend(f"「{loc}」在行程中重复出现 {c} 次" for loc, c in seen.items() if c > 1)

    return {"day_numbers": preserved_days}, {"day_numbers": changed_days}, warnings


class AgentResultAggregator:
    def aggregate(
        self,
        intent: IntentResult,
        step_results: List[StepResult],
        requirement_before: TravelRequirement,
        requirement_after: TravelRequirement,
        previous_itinerary: Optional[Itinerary],
        updated_itinerary: Optional[Itinerary],
        new_activity_candidates: List[dict],
        trace_id: str,
    ) -> AggregatedExecutionResult:
        requirement_changes = _diff_requirement(requirement_before, requirement_after)
        preserved_scope, changed_scope, warnings = _diff_itinerary(previous_itinerary, updated_itinerary, intent)

        unresolved = [sr.error for sr in step_results if not sr.success and sr.error]

        user_visible_summary = {
            "understood_request": intent.rewritten_request,
            "added_categories": intent.entities.add_categories,
            "removed_categories": intent.entities.remove_categories,
            "changed_days": changed_scope.get("day_numbers", []),
            "preserved_days": preserved_scope.get("day_numbers", []),
            "new_candidates": [c.get("name") for c in new_activity_candidates],
        }

        return AggregatedExecutionResult(
            requirement_changes=requirement_changes,
            new_activity_candidates=new_activity_candidates,
            updated_itinerary=updated_itinerary.model_dump() if updated_itinerary else None,
            preserved_scope=preserved_scope,
            changed_scope=changed_scope,
            warnings=warnings,
            unresolved_issues=unresolved,
            user_visible_summary=user_visible_summary,
            step_results=step_results,
            trace_id=trace_id,
        )
