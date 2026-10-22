"""SSE streaming chat endpoint (Stage-4).

`POST /api/chat/stream` drives the same LangGraph workflow as `POST /chat`
(`api/chat.py::run_chat_turn`), but tuned for a live frontend instead of a
scripted caller:

  - Never blocks on a research pass. If the turn would dispatch the research
    background job (see `execution/research_jobs.py`), it's dispatched and
    the stream closes immediately with one "researching" event; the frontend
    then polls `GET /api/research/status` and fetches the result via
    `GET /api/session/{id}` once the job reports `done` -- there's nothing to
    stream token-by-token at dispatch time since the actual research/summary
    text is produced later, off-request, in the background thread.
  - Streams token-level output for every other (synchronous) turn via
    `graph.stream(..., stream_mode="messages")` -- LangGraph surfaces token
    deltas for *any* chat-model call made inside a node automatically, even
    though node/agent code just calls plain `.invoke()` (verified live; no
    node or agent code needed to change for this).

Kept fully synchronous under the hood -- nothing in `nodes.py`/the agents
is `async`; only this module's request handling is, so FastAPI can stream
the response as it's produced instead of buffering the whole turn.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator, Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from travel_agent.api.chat import ChatRequest, _build_data_payload, _config_for, _RESEARCHING_RESPONSE
from travel_agent.execution import research_jobs
from travel_agent.graph.state import new_initial_state
from travel_agent.graph.workflow import get_compiled_graph

router = APIRouter()


def _sse(event: Dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _final_event(values: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "final",
        "response": values.get("pending_response", ""),
        "current_node": values.get("current_node", ""),
        "need_user_input": values.get("need_user_input", False),
        "data": _build_data_payload(values),
    }


def _stream_turn(session_id: str, message: str, user_id: Optional[str]) -> Iterator[str]:
    graph = get_compiled_graph()
    config = _config_for(session_id)
    from travel_agent.persistence import database
    user_id = database.current_user_id() or user_id
    user_id = database.current_user_id() or user_id
    if database.enabled():
        database.touch_session(session_id, user_id)

    if research_jobs.is_running(session_id):
        snapshot = graph.get_state(config)
        if snapshot.values.get("current_node") != "planner":
            # Preserve the established initial-research response contract.
            yield _sse(_final_event(snapshot.values))
        else:
            yield _sse({"type": "final", **_RESEARCHING_RESPONSE.model_dump()})
        return

    if research_jobs.retry_failed_if_paused(session_id, graph, config):
        yield _sse({"type": "final", **_RESEARCHING_RESPONSE.model_dump()})
        return

    existing_state = graph.get_state(config)
    is_new_session = existing_state is None or not existing_state.values

    if is_new_session:
        stream_input: Any = new_initial_state(session_id, message, user_id=user_id)
    else:
        graph.update_state(
            config,
            {"user_message": message, "conversation_history": [{"role": "user", "content": message}]},
        )
        stream_input = None

    for chunk, metadata in graph.stream(stream_input, config, stream_mode="messages"):
        content = getattr(chunk, "content", None)
        if content:
            yield _sse({"type": "token", "node": metadata.get("langgraph_node"), "content": content})

    snapshot = graph.get_state(config)
    if database.enabled():
        database.touch_session(session_id, user_id, snapshot.values.get("stage"))
    if tuple(snapshot.next) == (research_jobs.RESEARCH_PAUSE_NODE,):
        is_planner_expansion = snapshot.values.get("current_node") == "planner"
        research_jobs.dispatch_if_needed(session_id, graph, config)
        # The persisted state still contains the selection/planning node's
        # transition text. Returning it as `stage=planning` makes the browser
        # stop polling even though an expansion research job is running. The
        # frontend contract is explicit: every background-research pause is
        # surfaced as `researching`, regardless of whether it was initial
        # research or a Planner feasibility expansion.
        if is_planner_expansion:
            yield _sse({"type": "final", **_RESEARCHING_RESPONSE.model_dump()})
        else:
            yield _sse(_final_event(snapshot.values))
        return

    yield _sse(_final_event(snapshot.values))


@router.post("/api/chat/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    """SSE variant of `POST /chat` -- see module docstring."""
    return StreamingResponse(
        _stream_turn(req.session_id, req.message, req.user_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
