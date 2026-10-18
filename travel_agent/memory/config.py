"""Loads `config/memory.yaml`. Mirrors `travel_agent/rag/config.py` exactly:
pydantic model tree, `@lru_cache` keyed on `(path, mtime)`, all-defaults if
the file is missing.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict

import yaml
from pydantic import BaseModel


class MemoryConfig(BaseModel):
    max_working_messages: int = 12
    working_memory_ttl_seconds: int = 86400
    episodic_top_k: int = 5
    profile_top_k: int = 6
    episodic_importance_threshold: float = 0.3
    profile_stable_evidence_count: int = 3


def _default_config_path() -> str:
    return "./config/memory.yaml"


@lru_cache(maxsize=8)
def _load_cached(path: str, mtime: float) -> MemoryConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw: Dict[str, Any] = yaml.safe_load(f) or {}
    return MemoryConfig(**raw)


def load_memory_config(path: str | None = None) -> MemoryConfig:
    resolved_path = path or _default_config_path()
    try:
        mtime = os.path.getmtime(resolved_path)
    except OSError:
        return MemoryConfig()
    return _load_cached(resolved_path, mtime)
