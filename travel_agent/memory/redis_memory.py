"""Session state persistence interface.

Defines a small `SessionMemory` protocol-like class backed by Redis when
`REDIS_URL` is configured, and an in-process dict fallback otherwise. This is
used by the API layer to store auxiliary session metadata (e.g. display-
friendly conversation transcript) alongside LangGraph's own checkpointer,
which handles the authoritative graph state.

Swap `RedisSessionMemory` in once a Redis instance is available; the
interface (`get` / `set` / `delete`) does not need to change.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Dict, Optional, Protocol

from travel_agent.config.settings import get_settings


class SessionMemory(Protocol):
    def get(self, session_id: str) -> Optional[Dict[str, Any]]: ...

    def set(self, session_id: str, data: Dict[str, Any]) -> None: ...

    def delete(self, session_id: str) -> None: ...


class InMemorySessionMemory:
    """Thread-safe in-process fallback. Data is lost on process restart."""

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._store.get(session_id)

    def set(self, session_id: str, data: Dict[str, Any]) -> None:
        with self._lock:
            self._store[session_id] = data

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._store.pop(session_id, None)


class RedisSessionMemory:
    """Redis-backed session memory.

    Requires `redis` package and a reachable `REDIS_URL`. Falls back to
    raising at construction time if the client can't be created; callers
    should catch this and use `InMemorySessionMemory` instead (see
    `get_session_memory` below).
    """

    def __init__(self, redis_url: str, key_prefix: str, ttl_seconds: int) -> None:
        import redis  # imported lazily so the dependency is optional

        self._client = redis.Redis.from_url(redis_url, decode_responses=True)
        self._client.ping()
        self._prefix = key_prefix
        self._ttl = ttl_seconds

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        raw = self._client.get(self._key(session_id))
        return json.loads(raw) if raw else None

    def set(self, session_id: str, data: Dict[str, Any]) -> None:
        self._client.set(self._key(session_id), json.dumps(data, ensure_ascii=False), ex=self._ttl)

    def delete(self, session_id: str) -> None:
        self._client.delete(self._key(session_id))


def build_session_memory(key_prefix: str, ttl_seconds: int) -> SessionMemory:
    """Construct a `SessionMemory` with an arbitrary prefix/TTL, same
    graceful-degradation contract as `get_session_memory()` (Redis if
    `REDIS_URL` is set and reachable, in-memory fallback otherwise). Not
    cached -- callers that want a process-wide singleton build their own
    (see `get_session_memory()` below and `working_memory.py`'s
    `get_working_memory_store()`), since different callers legitimately want
    different prefixes/TTLs from the same underlying Redis instance."""
    settings = get_settings()
    if settings.redis_url:
        try:
            return RedisSessionMemory(settings.redis_url, key_prefix, ttl_seconds)
        except Exception:
            if settings.require_persistent_services:
                raise
            # Local development may fall back; production must fail loudly.
            pass
    if settings.require_persistent_services:
        raise RuntimeError("REDIS_URL is required for session memory")
    return InMemorySessionMemory()


_singleton: Optional[SessionMemory] = None


def get_session_memory() -> SessionMemory:
    """Return a process-wide SessionMemory instance (L1 conversation memory
    prefix/TTL, from `Settings`)."""
    global _singleton
    if _singleton is not None:
        return _singleton
    settings = get_settings()
    _singleton = build_session_memory(settings.redis_key_prefix, settings.redis_ttl_seconds)
    return _singleton
