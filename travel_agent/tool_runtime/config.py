"""Loads `config/tool_runtime.yaml` -- per-tool timeout/cache-ttl/circuit-
breaker thresholds. Mirrors `travel_agent/intent/config.py::load_fusion_config`
exactly: pydantic model tree, `@lru_cache` keyed on `(path, mtime)` so edits
are picked up without a restart, all-defaults if the file is missing.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict

import yaml
from pydantic import BaseModel, Field

from travel_agent.config.settings import get_settings


class CircuitBreakerConfig(BaseModel):
    failure_threshold: int = 5
    cooldown_seconds: float = 60.0


class ToolRuntimeEntry(BaseModel):
    timeout_seconds: float = 10.0
    cache_ttl_seconds: float = 0.0
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)


class ToolRuntimeConfig(BaseModel):
    default: ToolRuntimeEntry = Field(default_factory=ToolRuntimeEntry)
    tools: Dict[str, ToolRuntimeEntry] = Field(default_factory=dict)

    def for_tool(self, tool_name: str) -> ToolRuntimeEntry:
        return self.tools.get(tool_name, self.default)


def _default_config_path() -> str:
    return get_settings().tool_runtime_config_path


@lru_cache(maxsize=8)
def _load_cached(path: str, mtime: float) -> ToolRuntimeConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw: Dict[str, Any] = yaml.safe_load(f) or {}
    return ToolRuntimeConfig(**raw)


def load_tool_runtime_config(path: str | None = None) -> ToolRuntimeConfig:
    """Return the (cached, mtime-aware) tool-runtime config, or defaults if
    the file is missing -- the pipeline must still run with sane values even
    before `config/tool_runtime.yaml` is deployed to an environment."""
    resolved_path = path or _default_config_path()
    try:
        mtime = os.path.getmtime(resolved_path)
    except OSError:
        return ToolRuntimeConfig()
    return _load_cached(resolved_path, mtime)
