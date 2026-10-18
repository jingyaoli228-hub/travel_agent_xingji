"""Builds and compiles the LangGraph `StateGraph` for the travel agent.

Graph shape (Stage-2, Adaptive Agentic Workflow):

    START -> requirement_agent -[complete?]-> region_confirmation (complex dest only) -> user_confirmation -[confirmed?]-> research_orchestrator
                    |no                                                                        |no (correction)
                    v                                                                           v
              clarification <-------------------------------------------------------------------+
                    ^ (loop until complete)
                    |

    research_orchestrator -[initial/feedback]-> recommendation -> user_selection
                                                                        |free-text feedback -> research_orchestrator (scoped incremental)
                                                                        |selected -> planner
    planner -[feasible]-> validator -> reviewer -[score>=85 or max loops]-> strict_evaluation -[score>=65 or max revision rounds]-> final_output -> END
           |                                   -[else]-> planner  (loop, max `settings.max_review_loops`)                     -[else]-> planner  (loop, max `evaluation_criteria.yaml: max_revision_rounds`)
           |-[insufficient, under expansion-loop budget]-> research_orchestrator -[expansion]-> planner  (auto, no user turn)

    Round-6 Phase 6: `strict_evaluation` is a second, deeper gate after
    `reviewer` passes -- 8 dimensions + hard penalties + full memory/research
    context vs. `reviewer`'s fast 5-dim in-generation check (see
    `evaluation/llm_judge.py`'s module docstring). Its own revision loop back
    to `planner` is a separate budget (`revision_round`) from `reviewer`'s
    (`review_loop_count`); `final_output` shows improvement notes whenever the
    plan reached it below `pass_threshold` (80) -- either scored 65-79, or
    exhausted its revision budget below that -- instead of silently presenting
    it as if nothing were wrong (`evaluation/revision_router.py`).

Human-in-the-loop is implemented with LangGraph's `interrupt_before`: the
graph pauses execution right before `clarification`, `region_confirmation`,
`user_confirmation` and `user_selection` run, returning control to the API
layer. The API layer reads `need_user_input` / `pending_response` from the
paused state, shows it to the user, and resumes the graph (via
`update_state` + `invoke(None, config)`) once a new message arrives.
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from travel_agent.config.settings import get_settings
from travel_agent.graph.nodes import (
    clarification_node,
    constraint_builder_node,
    constraint_relaxation_node,
    clarify_post_plan_node,
    close_out_node,
    execution_router_node,
    final_output_node,
    intent_interpreter_node,
    planner_node,
    post_plan_feedback_node,
    recommendation_node,
    region_confirmation_node,
    requirement_agent_node,
    research_orchestrator_node,
    result_aggregation_node,
    reviewer_node,
    route_after_confirmation,
    route_after_execution_router,
    route_after_intent_interpreter,
    route_after_planner,
    route_after_post_plan_feedback,
    route_after_region_confirmation,
    route_after_requirement,
    route_after_research,
    route_after_reviewer,
    route_after_selection,
    route_after_strict_evaluation,
    side_query_node,
    strict_evaluation_node,
    tripcraft_metric_evaluator_node,
    route_after_metric_evaluator,
    user_confirmation_node,
    user_selection_node,
    validator_node,
)
from travel_agent.graph.state import AgentState

NODE_NAMES = [
    "requirement_agent",
    "clarification",
    "region_confirmation",
    "user_confirmation",
    "research_orchestrator",
    "recommendation",
    "user_selection",
    "planner",
    "validator",
    "reviewer",
    "strict_evaluation",
    "final_output",
    "post_plan_feedback",
    "close_out",
    "intent_interpreter",
    "clarify_post_plan",
    "side_query",
    "execution_router",
    "result_aggregation",
]

# Nodes that require a fresh user message before they can meaningfully run.
# `post_plan_feedback` is the single re-entrant interrupt point for the
# entire Stage-3 feedback loop -- every path in that loop (close_out,
# clarify_post_plan, side_query, result_aggregation) routes back to it, so
# the graph never reaches END after the first plan; it just keeps listening.
#
# `research_orchestrator` is Stage-4's *background-job* pause point, not a
# user-input one: it's reached from `user_confirmation` (initial research),
# `user_selection` ("更多"/feedback), and `planner` (the automatic feasibility
# expansion loop) alike. Pausing here means whichever `graph.invoke(...)` call
# would otherwise have blocked for the whole (now-parallelized, still
# multi-worker) research pass returns immediately instead; `travel_agent.
# execution.research_jobs` is what actually resumes it, from a background
# thread, so `/chat` doesn't have to wait (see `api/chat.py::run_chat_turn`).
INTERRUPT_BEFORE = [
    "clarification", "region_confirmation", "user_confirmation", "user_selection",
    "research_orchestrator", "post_plan_feedback",
]


def build_graph():
    """Construct (uncompiled) the travel agent StateGraph."""
    graph = StateGraph(AgentState)

    graph.add_node("requirement_agent", requirement_agent_node)
    graph.add_node("clarification", clarification_node)
    graph.add_node("region_confirmation", region_confirmation_node)
    graph.add_node("user_confirmation", user_confirmation_node)
    graph.add_node("research_orchestrator", research_orchestrator_node)
    graph.add_node("recommendation", recommendation_node)
    graph.add_node("user_selection", user_selection_node)
    graph.add_node("planner", planner_node)
    graph.add_node("validator", validator_node)
    graph.add_node("constraint_builder", constraint_builder_node)
    graph.add_node("tripcraft_metric_evaluator", tripcraft_metric_evaluator_node)
    graph.add_node("constraint_relaxation", constraint_relaxation_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("strict_evaluation", strict_evaluation_node)
    graph.add_node("final_output", final_output_node)
    graph.add_node("post_plan_feedback", post_plan_feedback_node)
    graph.add_node("close_out", close_out_node)
    graph.add_node("intent_interpreter", intent_interpreter_node)
    graph.add_node("clarify_post_plan", clarify_post_plan_node)
    graph.add_node("side_query", side_query_node)
    graph.add_node("execution_router", execution_router_node)
    graph.add_node("result_aggregation", result_aggregation_node)

    graph.add_edge(START, "requirement_agent")

    graph.add_conditional_edges(
        "requirement_agent",
        route_after_requirement,
        {
            "clarification": "clarification",
            "region_confirmation": "region_confirmation",
            "user_confirmation": "user_confirmation",
        },
    )
    graph.add_conditional_edges(
        "clarification",
        route_after_requirement,
        {
            "clarification": "clarification",
            "region_confirmation": "region_confirmation",
            "user_confirmation": "user_confirmation",
        },
    )
    graph.add_conditional_edges(
        "region_confirmation",
        route_after_region_confirmation,
        {"user_confirmation": "user_confirmation", "clarification": "clarification"},
    )
    graph.add_conditional_edges(
        "user_confirmation",
        route_after_confirmation,
        {
            "research_orchestrator": "constraint_builder",
            "clarification": "clarification",
            "user_confirmation": "user_confirmation",
        },
    )

    graph.add_edge("constraint_builder", "research_orchestrator")
    graph.add_conditional_edges(
        "research_orchestrator",
        route_after_research,
        {"recommendation": "recommendation", "planner": "planner"},
    )
    graph.add_edge("recommendation", "user_selection")
    graph.add_conditional_edges(
        "user_selection",
        route_after_selection,
        {"research_orchestrator": "research_orchestrator", "planner": "planner"},
    )

    graph.add_conditional_edges(
        "planner",
        route_after_planner,
        {"research_orchestrator": "research_orchestrator", "validator": "validator"},
    )
    graph.add_edge("validator", "tripcraft_metric_evaluator")
    graph.add_conditional_edges(
        "tripcraft_metric_evaluator",
        route_after_metric_evaluator,
        {"planner": "planner", "reviewer": "reviewer", "constraint_relaxation": "constraint_relaxation"},
    )
    graph.add_edge("constraint_relaxation", END)
    graph.add_conditional_edges(
        "reviewer",
        route_after_reviewer,
        {"planner": "planner", "strict_evaluation": "strict_evaluation"},
    )
    graph.add_conditional_edges(
        "strict_evaluation",
        route_after_strict_evaluation,
        {"planner": "planner", "final_output": "final_output"},
    )

    graph.add_edge("final_output", "post_plan_feedback")
    graph.add_conditional_edges(
        "post_plan_feedback",
        route_after_post_plan_feedback,
        {"close_out": "close_out", "intent_interpreter": "intent_interpreter"},
    )
    graph.add_edge("close_out", "post_plan_feedback")
    graph.add_conditional_edges(
        "intent_interpreter",
        route_after_intent_interpreter,
        {
            "clarify_post_plan": "clarify_post_plan",
            "side_query": "side_query",
            "execution_router": "execution_router",
        },
    )
    graph.add_edge("clarify_post_plan", "post_plan_feedback")
    graph.add_edge("side_query", "post_plan_feedback")
    graph.add_conditional_edges(
        "execution_router", route_after_execution_router, {"result_aggregation": "result_aggregation"},
    )
    graph.add_edge("result_aggregation", "post_plan_feedback")

    return graph


@lru_cache
def get_compiled_graph():
    """Return the graph with PostgreSQL checkpoints in production."""
    graph = build_graph()
    settings = get_settings()
    if settings.database_url:
        # Keep the context manager alive for the process lifetime.  Both API
        # and worker own one connection/pool and share checkpoints through PG.
        from langgraph.checkpoint.postgres import PostgresSaver

        manager = PostgresSaver.from_conn_string(settings.database_url)
        checkpointer = manager.__enter__()
        checkpointer.setup()
        _checkpointer_managers.append(manager)
    else:
        if settings.require_persistent_services:
            raise RuntimeError("DATABASE_URL is required when REQUIRE_PERSISTENT_SERVICES=true")
        checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer, interrupt_before=INTERRUPT_BEFORE)


_checkpointer_managers: list[object] = []
