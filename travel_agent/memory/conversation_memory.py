"""L1 Conversation Memory.

Lifecycle: the current trip (one `session_id`). Backed by the *existing*
`SessionMemory` (`travel_agent/memory/redis_memory.py`) which is already
Redis-backed with an in-memory fallback -- reused as-is rather than building
a second storage layer.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from travel_agent.memory.redis_memory import get_session_memory
from travel_agent.schemas.memory import ConversationMemoryRecord

_KEY_PREFIX = "conv:"


class ConversationMemory:
    """L1 accessor: one `ConversationMemoryRecord` per session."""

    def __init__(self) -> None:
        self._store = get_session_memory()

    def _key(self, session_id: str) -> str:
        return f"{_KEY_PREFIX}{session_id}"

    def get(self, session_id: str) -> Optional[ConversationMemoryRecord]:
        data = self._store.get(self._key(session_id))
        return ConversationMemoryRecord(**data) if data else None

    def update(
        self,
        session_id: str,
        original_request: Optional[str] = None,
        confirmed_requirement: Optional[Dict[str, Any]] = None,
        user_choice: Optional[str] = None,
        rejected_option: Optional[str] = None,
    ) -> ConversationMemoryRecord:
        record = self.get(session_id) or ConversationMemoryRecord(session_id=session_id)
        if original_request is not None and not record.original_request:
            record.original_request = original_request
        if confirmed_requirement is not None:
            record.confirmed_requirement = confirmed_requirement
        if user_choice:
            record.user_choices.append(user_choice)
        if rejected_option:
            record.rejected_options.append(rejected_option)
        record.current_version += 1
        self._store.set(self._key(session_id), record.model_dump())
        return record

    def list_user_choices(self, session_id: str) -> List[str]:
        record = self.get(session_id)
        return record.user_choices if record else []
