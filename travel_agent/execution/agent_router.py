"""`AgentRouter` (design doc section 13): executes an `ExecutionPlan`'s steps
against the four existing agent instances. Serial by construction --
Requirement -> Research -> Planner have a real data dependency in every
scenario this upgrade targets (a patched preference must reach Research
before Research's output can reach the Planner), so there is nothing
meaningful to parallelize here; the design doc's "partial parallel steps"
allowance is a non-goal for this pass. One step failing is caught and
recorded as a failed `StepResult` instead of aborting the remaining steps.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from travel_agent.agents.planner_agent import PlannerAgent
from travel_agent.agents.requirement_agent import RequirementAgent
from travel_agent.agents.research_agent import ResearchOrchestratorAgent
from travel_agent.destination_intelligence.service import DestinationIntelligenceService
from travel_agent.execution.region_resolution import resolve_target_days_for_region
from travel_agent.execution.schemas import ExecutionPlan, StepResult
from travel_agent.intent.pattern_parser import canonicalize_categories
from travel_agent.intent.schemas import IntentResult
from travel_agent.schemas.itinerary import Itinerary
from travel_agent.schemas.research_result import ResearchResult
from travel_agent.schemas.travel_requirement import TravelRequirement
from travel_agent.utils.logging import get_logger

_logger = get_logger("travel_agent.execution.agent_router")


def apply_state_patch(requirement: TravelRequirement, patch: Dict[str, Any]) -> TravelRequirement:
    """Turn a structured `state_patch` (see fusion_resolver.state_patch_from_feedback)
    into a concrete `TravelRequirement` update -- never free text."""
    updated = requirement.model_copy(deep=True)
    add_prefs = patch.get("preferences_to_add") or []
    reduce_prefs = patch.get("preferences_to_reduce") or []
    if add_prefs:
        updated.experience_preferences = list(dict.fromkeys(list(updated.experience_preferences) + add_prefs))
    if reduce_prefs:
        updated.experience_preferences = [p for p in updated.experience_preferences if p not in reduce_prefs]
    if "daily_attraction_count_delta" in patch:
        current = updated.daily_attraction_count or 3
        updated.daily_attraction_count = max(1, current + int(patch["daily_attraction_count_delta"]))
    if patch.get("prefer_cheap"):
        updated.constraints = list(dict.fromkeys(updated.constraints + ["预算收紧，优先经济型选择"]))
    if patch.get("prefer_niche"):
        updated.constraints = list(dict.fromkeys(updated.constraints + ["偏好小众/本地化体验"]))
    if patch.get("transport_preference"):
        updated.constraints = list(dict.fromkeys(updated.constraints + [f"交通偏好：{patch['transport_preference']}"]))
    return updated


def _extend_selection(
    selected: Dict[str, List[dict]], research: ResearchResult, categories: List[str], quantity: Optional[int]
) -> Tuple[Dict[str, List[dict]], List[dict]]:
    selected_names = {e["name"] for e in selected.get("experiences", [])}
    candidates = [e for e in research.experiences if (not categories or e.type in categories) and e.name not in selected_names]
    limit = quantity if quantity else max(len(categories) * 2, 2)
    picked = candidates[:limit]
    picked_dicts = [e.model_dump() for e in picked]
    new_selected = {"experiences": list(selected.get("experiences", [])) + picked_dicts}
    return new_selected, picked_dicts


class AgentRouter:
    def __init__(
        self,
        requirement_agent: RequirementAgent,
        research_agent: ResearchOrchestratorAgent,
        planner_agent: PlannerAgent,
    ) -> None:
        self._requirement_agent = requirement_agent
        self._research_agent = research_agent
        self._planner_agent = planner_agent
        # Stateless (LLM passed in per-call, see DestinationIntelligenceService's
        # own docstring) -- reuses RequirementAgent's already-constructed LLM
        # client rather than building its own, same "no module constructs its
        # own client" rule as everywhere else.
        self._destination_intelligence = DestinationIntelligenceService()

    def run(
        self,
        plan: ExecutionPlan,
        intent: IntentResult,
        requirement: TravelRequirement,
        research: ResearchResult,
        selected: Dict[str, List[dict]],
        previous_itinerary: Optional[Itinerary],
        profile_hint: Optional[dict] = None,
    ) -> Tuple[TravelRequirement, ResearchResult, Dict[str, List[dict]], Optional[Itinerary], List[dict], List[StepResult]]:
        step_results: List[StepResult] = []
        new_candidates: List[dict] = []
        itinerary = previous_itinerary

        for step in plan.steps:
            try:
                if step.agent == "RequirementAgent":
                    requirement = apply_state_patch(requirement, intent.state_patch)
                    step_results.append(
                        StepResult(step=step.step, agent=step.agent, action=step.action, output={"state_patch": intent.state_patch})
                    )

                elif step.agent == "ResearchOrchestrator":
                    raw_categories = (
                        intent.entities.add_categories
                        or intent.entities.region_focus
                        or intent.state_patch.get("preferences_to_add")
                        or []
                    )
                    categories = canonicalize_categories(raw_categories)
                    # A region-replacement's activities live in the NEW
                    # (target) region, not whatever `entities.region` was --
                    # that field is for the older single-region use cases
                    # (COMPARE_REGIONS etc), see intent/schemas.py.
                    search_region = intent.entities.target_region or intent.entities.region
                    region_candidate = None
                    if intent.entities.target_region:
                        # Ask Destination Intelligence what this region is
                        # actually known for (Phase 4) BEFORE searching, so
                        # the query generator (Phase 5) can search the
                        # region's own signature experiences instead of only
                        # the user's literal wording.
                        region_candidate = self._destination_intelligence.profile_region(
                            requirement.destination or "",
                            intent.entities.target_region,
                            focus_hint=intent.entities.region_focus or None,
                            llm=self._requirement_agent._llm,
                            system_prompt=self._requirement_agent._system_prompt,
                        )
                    research = self._research_agent.run_expansion(
                        requirement, research, categories, region=search_region, region_candidate=region_candidate,
                    )
                    selected, picked = _extend_selection(selected, research, categories, intent.entities.quantity)
                    new_candidates.extend(picked)
                    step_results.append(
                        StepResult(step=step.step, agent=step.agent, action=step.action, output={"new_activity_count": len(picked)})
                    )

                elif step.agent == "PlannerAgent":
                    target_region = intent.entities.target_region
                    if intent.entities.day_index:
                        target_days = [intent.entities.day_index]
                    elif target_region and intent.entities.source_region:
                        target_days = resolve_target_days_for_region(itinerary, intent.entities.source_region)
                    else:
                        target_days = []

                    # A region swap is a partial-replan by definition (see
                    # pattern_parser._extract_region_replacement) even
                    # without an explicit "preserve other days" phrase --
                    # `preserve_other_days` already defaults True for it at
                    # the Pattern layer, but an LLM-sourced entities object
                    # might not carry that default, so `target_region` alone
                    # is also sufficient to choose the partial path here.
                    if itinerary is not None and target_days and (intent.entities.preserve_other_days or target_region):
                        region_overrides = {d: target_region for d in target_days} if target_region else None
                        itinerary = self._planner_agent.run_partial(
                            requirement,
                            itinerary,
                            research,
                            selected,
                            target_days=target_days,
                            target_time_periods=[intent.entities.time_period] if intent.entities.time_period else None,
                            profile_hint=profile_hint,
                            region_overrides=region_overrides,
                        )
                    else:
                        itinerary, _feasibility = self._planner_agent.run(
                            requirement, selected, research, previous_itinerary=itinerary, profile_hint=profile_hint,
                        )
                    step_results.append(
                        StepResult(step=step.step, agent=step.agent, action=step.action, output={"day_count": len(itinerary.days)})
                    )

                elif step.agent == "PresentationAgent":
                    # Formatting itself happens in AgentResultAggregator/graph
                    # node -- this step exists so it appears in the trace.
                    step_results.append(StepResult(step=step.step, agent=step.agent, action=step.action, output={}))

            except Exception as exc:  # noqa: BLE001 - one step failing shouldn't abort the whole chain
                _logger.warning("Execution step %s (%s) failed: %s", step.step, step.agent, exc)
                step_results.append(StepResult(step=step.step, agent=step.agent, action=step.action, success=False, error=str(exc)))

        return requirement, research, selected, itinerary, new_candidates, step_results
