"""LangGraph shared state definition.

All agent nodes read/write this single `AgentState`. Complex objects
(TravelRequirement, ResearchResult, Itinerary, ReviewReport) are stored as
plain dicts (via `.model_dump()`) so the state stays JSON-serializable,
which is required for LangGraph checkpointers (including future Redis/
Postgres-backed ones). This IS L0 Working Memory (see
`travel_agent/memory/working_memory.py`) -- there is no separate storage
layer for it.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict


class AgentState(TypedDict, total=False):
    # -- session / conversation --
    session_id: str
    user_id: str
    conversation_history: Annotated[List[Dict[str, str]], operator.add]
    user_message: str

    # -- requirement stage --
    travel_requirement: Optional[Dict[str, Any]]
    requirement_summary: str
    confirmed_fields: List[str]
    missing_fields: List[str]
    destination_assessment: Optional[Dict[str, Any]]
    user_profile_hint: Optional[Dict[str, Any]]

    # -- research stage --
    research_result: Optional[Dict[str, Any]]
    research_mode: str  # "initial" | "feedback" | "feedback_auto_select" | "expansion"
    research_feedback_message: Optional[str]
    # Round-6: explicit activity topics parsed out of a selection-stage reply
    # (see graph/nodes.py::user_selection_node) -- lets research_orchestrator_
    # node search for all of them via QueryGenerator instead of
    # parse_feedback_intent's single-category heuristic.
    research_feedback_topics: Optional[List[str]]
    # Round-6: the same reply also said "you decide" -- once the topic-scoped
    # research above comes back, auto-select from it and go straight to
    # planning (route_after_research) instead of pausing to show candidates.
    auto_select_after_feedback: bool

    # -- candidate selection stage --
    candidates: Optional[Dict[str, Any]]
    selected_places: Optional[Dict[str, Any]]

    # -- planning stage --
    itinerary: Optional[Dict[str, Any]]
    plan_feasibility: Optional[Dict[str, Any]]
    expansion_loop_count: int
    travel_constraints: Optional[Dict[str, Any]]
    planner_attempt: int
    metric_report: Optional[Dict[str, Any]]
    metric_history: List[Dict[str, Any]]
    best_plan: Optional[Dict[str, Any]]
    best_metric_report: Optional[Dict[str, Any]]
    constraint_violations: List[Dict[str, Any]]
    repair_targets: List[Dict[str, Any]]
    needs_constraint_relaxation: bool
    hotel_selection_status: str
    hotel_candidates_by_city: Dict[str, Any]
    selected_hotels_by_city: Dict[str, Any]
    plan_version: int

    # -- review stage --
    rule_issues: List[str]
    review_report: Optional[Dict[str, Any]]
    review_loop_count: int

    # -- Round-6 Phase 6: strict evaluation (see evaluation/llm_judge.py) --
    # `revision_round` is `strict_evaluation`'s own loop counter, independent
    # of `review_loop_count` above (the fast 5-dim reviewer gate) -- see
    # `graph/nodes.py::strict_evaluation_node`'s docstring for why these two
    # gates don't share a counter.
    strict_evaluation: Optional[Dict[str, Any]]
    revision_round: int

    # -- final output --
    final_plan: Optional[Dict[str, Any]]

    # -- Stage-3: post-plan feedback loop (multi-signal intent + execution chain) --
    intent_result: Optional[Dict[str, Any]]
    aggregated_result: Optional[Dict[str, Any]]

    # -- Round-6 Phase 5: unified Memory Context (see memory/context_builder.py) --
    # Built once per turn where it matters (requirement/research stages) and
    # read by later nodes in the same turn, rather than each node querying
    # memory separately. `travel_agent.memory.schemas.MemoryContext`, serialized.
    memory_context: Optional[Dict[str, Any]]

    # -- control / routing --
    stage: str  # requirement | clarification | region_confirmation | confirmation | research | selection
    # | planning | review | done | post_plan_feedback
    current_node: str
    need_user_input: bool
    pending_response: str


def new_initial_state(session_id: str, user_message: str, user_id: Optional[str] = None) -> AgentState:
    """Build the initial state for a brand-new session."""
    return AgentState(
        session_id=session_id,
        user_id=user_id or session_id,
        conversation_history=[{"role": "user", "content": user_message}],
        user_message=user_message,
        travel_requirement=None,
        requirement_summary="",
        confirmed_fields=[],
        missing_fields=[],
        destination_assessment=None,
        user_profile_hint=None,
        research_result=None,
        research_mode="initial",
        research_feedback_message=None,
        research_feedback_topics=None,
        auto_select_after_feedback=False,
        candidates=None,
        selected_places=None,
        itinerary=None,
        plan_feasibility=None,
        expansion_loop_count=0,
        travel_constraints=None,
        planner_attempt=0,
        metric_report=None,
        metric_history=[],
        best_plan=None,
        best_metric_report=None,
        constraint_violations=[],
        repair_targets=[],
        needs_constraint_relaxation=False,
        hotel_selection_status="NOT_STARTED",
        hotel_candidates_by_city={},
        selected_hotels_by_city={},
        plan_version=1,
        rule_issues=[],
        review_report=None,
        review_loop_count=0,
        strict_evaluation=None,
        revision_round=0,
        final_plan=None,
        intent_result=None,
        aggregated_result=None,
        memory_context=None,
        stage="requirement",
        current_node="requirement_agent",
        need_user_input=False,
        pending_response="",
    )
