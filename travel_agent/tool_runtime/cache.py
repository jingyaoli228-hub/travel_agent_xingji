"""In-process TTL cache for tool results, keyed by a hash of
`(tool_name, normalized_kwargs)`.

No Redis/`cachetools` dependency: this mirrors the project's existing
graceful-degradation style (Redis is reserved for session-state persistence,
`settings.redis_url`, not tool-result caching). Normalization here is
structural only (sorted keys, trimmed/lowercased string values) -- it does
NOT do cross-language semantic normalization (e.g. "Tokyo weather" vs
"东京天气" still miss each other), which would require an embedding/translation
call and would defeat the point of a cheap cache lookup.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, Optional, Tuple


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, dict):
        return {k: _normalize_value(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_normalize_value(v) for v in value]
    return value


def build_cache_key(tool_name: str, kwargs: Dict[str, Any]) -> str:
    normalized = _normalize_value(kwargs or {})
    payload = json.dumps({"tool": tool_name, "params": normalized}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CacheStore:
    """Simple in-process `{key: (value, expires_at)}` TTL cache."""

    def __init__(self) -> None:
        self._data: Dict[str, Tuple[Any, float]] = {}

    def get(self, tool_name: str, kwargs: Dict[str, Any]) -> Optional[Any]:
        key = build_cache_key(tool_name, kwargs)
        entry = self._data.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.time() > expires_at:
            self._data.pop(key, None)
            return None
        return value

    def set(self, tool_name: str, kwargs: Dict[str, Any], value: Any, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return
        key = build_cache_key(tool_name, kwargs)
        self._data[key] = (value, time.time() + ttl_seconds)

    def clear(self) -> None:
        self._data.clear()
