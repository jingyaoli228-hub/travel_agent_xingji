"""L0 Working Memory: now actually persisted, not just an in-process view.

Previously this module only exposed a stateless `snapshot()`/
`pending_field_questions()` reading of `AgentState` with no storage of its
own (see git history) -- and nothing in the codebase actually called them
yet. Requirement doc section 16 asks for a real Redis-backed layer (24h TTL,
key `travel:session:{session_id}:working_memory`), so this upgrade adds
`load()`/`save()`/`update_from_state()` on top of the *existing*
`redis_memory.py` machinery (`build_session_memory()`, reused as-is with a
distinct prefix/TTL from L1's `get_session_memory()` singleton -- same Redis
instance, different key namespace and retention).

`pending_field_questions()` is kept unchanged -- a small, independent, still
useful pure helper.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from travel_agent.memory.config import load_memory_config
from travel_agent.memory.redis_memory import SessionMemory, build_session_memory
from travel_agent.memory.schemas import WorkingMemory

_KEY_PREFIX = "travel:session:"
_KEY_SUFFIX = ":working_memory"

_store_singleton: Optional[SessionMemory] = None


def get_working_memory_store() -> SessionMemory:
    global _store_singleton
    if _store_singleton is None:
        config = load_memory_config()
        _store_singleton = build_session_memory(_KEY_PREFIX, config.working_memory_ttl_seconds)
    return _store_singleton


def _key(session_id: str) -> str:
    return f"{session_id}{_KEY_SUFFIX}"


def load(session_id: str) -> Optional[WorkingMemory]:
    data = get_working_memory_store().get(_key(session_id))
    return WorkingMemory(**data) if data else None


def save(working_memory: WorkingMemory) -> None:
    config = load_memory_config()
    if len(working_memory.recent_messages) > config.max_working_messages:
        working_memory.recent_messages = working_memory.recent_messages[-config.max_working_messages :]
    working_memory.updated_at = datetime.now(timezone.utc).isoformat()
    get_working_memory_store().set(_key(working_memory.session_id), working_memory.model_dump())


def append_message(session_id: str, user_id: str, role: str, content: str) -> WorkingMemory:
    wm = load(session_id) or WorkingMemory(session_id=session_id, user_id=user_id)
    wm.recent_messages.append({"role": role, "content": content})
    save(wm)
    return wm


def update_from_state(state: Dict[str, Any]) -> WorkingMemory:
    """Refresh the persisted `WorkingMemory` from the current `AgentState`
    (see `graph/state.py` for the field names read here). Not yet called
    from `graph/nodes.py` -- wiring this into the live graph is Phase 5's
    job (every agent reading from one shared `MemoryContext`); this function
    is what Phase 5 will call per turn."""
    session_id = state.get("session_id", "")
    wm = load(session_id) or WorkingMemory(session_id=session_id)
    wm.user_id = state.get("user_id") or wm.user_id
    wm.current_intent = state.get("intent_result")
    wm.travel_requirement = state.get("travel_requirement")
    wm.planning_state = state.get("itinerary")
    wm.visible_candidates = list((state.get("candidates") or {}).values()) if isinstance(state.get("candidates"), dict) else []
    wm.pending_confirmation = {"question": state.get("pending_response")} if state.get("need_user_input") else None
    save(wm)
    return wm


def pending_field_questions(state: Dict[str, Any]) -> List[str]:
    """Missing-field questions still open in this execution, if any."""
    return list(state.get("missing_fields") or [])
