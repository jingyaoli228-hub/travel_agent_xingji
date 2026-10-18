"""FastAPI chat endpoint.

Exposes `POST /chat`, the single entry point driving the whole multi-turn
LangGraph workflow. Session state is authoritatively persisted by
LangGraph's checkpointer (keyed by `session_id` as the `thread_id`); this
module is only responsible for (1) detecting whether a session is new or
resuming, (2) injecting the new user message, and (3) shaping the response.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from travel_agent.execution import research_jobs
from travel_agent.graph.state import new_initial_state
from travel_agent.graph.workflow import get_compiled_graph

router = APIRouter()


class ChatRequest(BaseModel):
    session_id: str = Field(..., description="会话 ID，用于标识一个持续的多轮对话")
    message: str = Field(..., description="用户输入的自然语言消息")
    user_id: Optional[str] = Field(
        default=None, description="用户 ID，用于跨会话的 L2/L3 长期记忆；缺省时退回使用 session_id"
    )


class ChatResponse(BaseModel):
    response: str
    current_node: str
    need_user_input: bool
    data: Dict[str, Any] = Field(default_factory=dict)


def _config_for(session_id: str) -> Dict[str, Any]:
    return {"configurable": {"thread_id": session_id}}


def _build_data_payload(values: Dict[str, Any]) -> Dict[str, Any]:
    """Only surface the state slices relevant to the current stage."""
    stage = values.get("stage")
    data: Dict[str, Any] = {"stage": stage}

    if values.get("travel_requirement"):
        data["travel_requirement"] = values["travel_requirement"]
    if stage in ("selection",) and values.get("candidates"):
        data["candidates"] = values["candidates"]
    if values.get("selected_places"):
        data["selected_places"] = values["selected_places"]
    if values.get("itinerary"):
        data["itinerary"] = values["itinerary"]
    if values.get("review_report"):
        data["review_report"] = values["review_report"]
    if values.get("final_plan"):
        data["final_plan"] = values["final_plan"]
    if stage == "post_plan_feedback":
        if values.get("intent_result"):
            data["intent_result"] = values["intent_result"]
        if values.get("aggregated_result"):
            data["aggregated_result"] = values["aggregated_result"]
    return data


_RESEARCHING_RESPONSE = ChatResponse(
    response="还在为您搜索中，请稍候...",
    current_node="research_orchestrator",
    need_user_input=False,
    data={"stage": "researching"},
)


def _snapshot_response(graph: Any, config: Dict[str, Any]) -> ChatResponse:
    """Read-only fetch of the current graph state, no new message injected."""
    snapshot = graph.get_state(config)
    values = snapshot.values if snapshot else {}
    return ChatResponse(
        response=values.get("pending_response", ""),
        current_node=values.get("current_node", ""),
        need_user_input=values.get("need_user_input", False),
        data=_build_data_payload(values),
    )


def run_chat_turn(
    session_id: str, message: str, user_id: Optional[str] = None, wait_for_research: bool = True
) -> ChatResponse:
    """Core logic shared by the HTTP endpoints, `demo.py`, `main.py` and tests.

    Stage-4: the (now parallelized, see `ResearchOrchestratorAgent.run_full`)
    research pass runs as a background job (`execution/research_jobs.py`)
    instead of inline inside this call, so it doesn't block whichever thread
    is driving the conversation. `wait_for_research` controls how *this*
    call relates to that job:
      - `True` (default): block until the job finishes, then return the
        resulting state -- preserves the exact pre-Stage-4 synchronous
        contract every existing caller (CLI/`demo.py`/tests) already
        depends on; they just get there faster now.
      - `False` (used by the streaming-aware frontend endpoints): return
        immediately with a "researching" status once the job is dispatched,
        so the caller can poll `GET /api/research/status` instead of
        blocking the request.
    A message arriving for a session whose job is still running is *not*
    injected into the graph (it would race the background thread's own
    `graph.invoke` for the same `thread_id`) -- non-waiting callers get told
    to wait; waiting callers simply wait out the existing job first.
    """
    graph = get_compiled_graph()
    config = _config_for(session_id)
    from travel_agent.persistence import database
    if database.enabled():
        database.touch_session(session_id, user_id)

    if research_jobs.is_running(session_id):
        if not wait_for_research:
            return _RESEARCHING_RESPONSE
        research_jobs.wait_until_done(session_id)
        return _snapshot_response(graph, config)

    if research_jobs.retry_failed_if_paused(session_id, graph, config):
        if not wait_for_research:
            return _RESEARCHING_RESPONSE
        research_jobs.wait_until_done(session_id)
        return _snapshot_response(graph, config)

    existing_state = graph.get_state(config)
    is_new_session = existing_state is None or not existing_state.values

    if is_new_session:
        initial_state = new_initial_state(session_id, message, user_id=user_id)
        graph.invoke(initial_state, config)
    else:
        graph.update_state(
            config,
            {"user_message": message, "conversation_history": [{"role": "user", "content": message}]},
        )
        graph.invoke(None, config)

    snapshot = graph.get_state(config)
    if tuple(snapshot.next) == (research_jobs.RESEARCH_PAUSE_NODE,):
        is_planner_expansion = snapshot.values.get("current_node") == "planner"
        research_jobs.dispatch_if_needed(session_id, graph, config)
        if not wait_for_research:
            return _RESEARCHING_RESPONSE if is_planner_expansion else _snapshot_response(graph, config)
        research_jobs.wait_until_done(session_id)
        return _snapshot_response(graph, config)

    values = snapshot.values
    if database.enabled():
        database.touch_session(session_id, user_id, values.get("stage"))
    return ChatResponse(
        response=values.get("pending_response", ""),
        current_node=values.get("current_node", ""),
        need_user_input=values.get("need_user_input", False),
        data=_build_data_payload(values),
    )


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """Single entry point for the multi-turn travel planning conversation.

    Blocks until the turn (including any research pass) fully completes --
    kept as the original synchronous contract for existing consumers. The
    frontend uses `POST /api/chat/stream` (non-blocking research + SSE token
    streaming) instead; see `travel_agent/api/chat_stream.py`.
    """
    return run_chat_turn(req.session_id, req.message, user_id=req.user_id)


@router.get("/api/research/status")
def research_status(session_id: str) -> Dict[str, Any]:
    """Live per-worker progress for an in-flight (or just-finished) research
    background job -- `{"status": "idle"|"running"|"done"|"error", "progress":
    {"amap_places": "running"|"done", ...}}`. Polled by the frontend while
    `stage in ("research", "researching", "selection")` and a job is running."""
    status = research_jobs.get_status(session_id)
    # Self-heal sessions produced by the old SSE contract or by a process
    # reload: the graph can still be paused before research while the
    # in-memory job registry says idle/done. Polling is sufficient to resume
    # it; the user does not need to send another chat message.
    if status.get("status") != "running":
        graph = get_compiled_graph()
        config = _config_for(session_id)
        if research_jobs.dispatch_if_needed(session_id, graph, config):
            status = research_jobs.get_status(session_id)
    return status


@router.get("/api/session/{session_id}", response_model=ChatResponse)
def get_session(session_id: str) -> ChatResponse:
    """Read-only fetch of the current conversation state, no new message
    injected -- used by the frontend once `/api/research/status` reports
    `done` to pick up the resulting candidates/itinerary message."""
    graph = get_compiled_graph()
    config = _config_for(session_id)
    snapshot = graph.get_state(config)
    if snapshot is None or not snapshot.values:
        raise HTTPException(status_code=404, detail=f"No session found for session_id={session_id!r}")
    return _snapshot_response(graph, config)
