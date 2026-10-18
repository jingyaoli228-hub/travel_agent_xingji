"""Tests for the Phase-1 Tool Runtime middleware (`travel_agent/tool_runtime/`):
cache TTL, circuit-breaker state transitions, timeout/exception handling,
JSON-schema parameter validation, fallback handling, and -- critically --
that `stub_external_calls`'s existing `monkeypatch.setattr(tool, "func", ...)`
mocking strategy still works once calls go through `ToolManager`.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import pytest
from pydantic import BaseModel

from travel_agent.tool_runtime.cache import CacheStore, build_cache_key
from travel_agent.tool_runtime.circuit_breaker import CLOSED, HALF_OPEN, OPEN, CircuitBreaker
from travel_agent.tool_runtime.manager import ToolManager


class _FakeArgs(BaseModel):
    query: str
    limit: int = 5


class _FakeTool:
    """Minimal stand-in for a LangChain `@tool` object: has `.invoke()` and
    (optionally) `.args_schema`, and counts calls so tests can assert the
    underlying function was/wasn't actually invoked."""

    def __init__(self, fn, args_schema=None):
        self._fn = fn
        self.args_schema = args_schema
        self.calls = 0

    def invoke(self, kwargs: Dict[str, Any]) -> Any:
        self.calls += 1
        return self._fn(**kwargs)


def _ok_dict(**kwargs) -> Dict[str, Any]:
    return {"success": True, "echo": kwargs}


def _failing_dict(**kwargs) -> Dict[str, Any]:
    return {"success": False, "error": "business failure"}


def _raising(**kwargs) -> Dict[str, Any]:
    raise RuntimeError("boom")


def _slow(**kwargs) -> Dict[str, Any]:
    time.sleep(0.3)
    return {"success": True}


# -- CacheStore -------------------------------------------------------------


def test_cache_ttl_expiry():
    cache = CacheStore()
    cache.set("tool.a", {"q": "x"}, {"value": 1}, ttl_seconds=0.05)
    assert cache.get("tool.a", {"q": "x"}) == {"value": 1}
    time.sleep(0.08)
    assert cache.get("tool.a", {"q": "x"}) is None


def test_cache_key_normalizes_whitespace_and_case():
    key_a = build_cache_key("tool.a", {"Query": " Tokyo "})
    key_b = build_cache_key("tool.a", {"Query": "tokyo"})
    assert key_a == key_b


# -- CircuitBreaker -----------------------------------------------------------


def test_circuit_breaker_opens_after_threshold_then_half_opens_after_cooldown():
    breaker = CircuitBreaker()
    name = "tool.b"
    assert breaker.allow(name, failure_threshold=2, cooldown_seconds=0.05) is True

    breaker.record_failure(name, failure_threshold=2)
    assert breaker.snapshot(name)["state"] == CLOSED
    breaker.record_failure(name, failure_threshold=2)
    assert breaker.snapshot(name)["state"] == OPEN

    assert breaker.allow(name, failure_threshold=2, cooldown_seconds=0.05) is False
    time.sleep(0.08)
    assert breaker.allow(name, failure_threshold=2, cooldown_seconds=0.05) is True
    assert breaker.snapshot(name)["state"] == HALF_OPEN

    breaker.record_success(name)
    assert breaker.snapshot(name)["state"] == CLOSED


# -- ToolManager --------------------------------------------------------------


def test_tool_manager_success_returns_same_shape_and_caches():
    tool = _FakeTool(_ok_dict)
    manager = ToolManager()
    result = manager.call(tool, {"q": "tokyo"}, tool_name="test.echo", cache_ttl=10)
    assert result == {"success": True, "echo": {"q": "tokyo"}}
    assert tool.calls == 1

    # second call with the same params hits the cache -- underlying tool not re-invoked
    result2 = manager.call(tool, {"q": "tokyo"}, tool_name="test.echo", cache_ttl=10)
    assert result2 == result
    assert tool.calls == 1


def test_tool_manager_timeout_returns_degraded_shape_not_raise():
    tool = _FakeTool(_slow)
    manager = ToolManager()
    result = manager.call(tool, {}, tool_name="test.slow", timeout=0.05)
    assert result["success"] is False
    assert result["status"] == "DEGRADED"


def test_tool_manager_exception_returns_degraded_shape_not_raise():
    tool = _FakeTool(_raising)
    manager = ToolManager()
    result = manager.call(tool, {}, tool_name="test.raises", timeout=1)
    assert result["success"] is False
    assert result["status"] == "DEGRADED"


def test_tool_manager_validation_error_skips_execution():
    tool = _FakeTool(_ok_dict, args_schema=_FakeArgs)
    manager = ToolManager()
    result = manager.call(tool, {"limit": 5}, tool_name="test.validated", timeout=1)  # missing required "query"
    assert result["status"] == "INVALID_PARAMETER"
    assert tool.calls == 0


def test_tool_manager_fallback_used_on_business_failure():
    tool = _FakeTool(_failing_dict)
    manager = ToolManager()
    result = manager.call(
        tool, {}, tool_name="test.fails", timeout=1, fallback=lambda: {"success": True, "status": "DEGRADED", "fallback": True}
    )
    assert result == {"success": True, "status": "DEGRADED", "fallback": True}


def test_tool_manager_fallback_used_on_exception():
    tool = _FakeTool(_raising)
    manager = ToolManager()
    result = manager.call(tool, {}, tool_name="test.raises2", timeout=1, fallback=lambda: {"success": True, "fallback": True})
    assert result == {"success": True, "fallback": True}


def test_tool_manager_circuit_breaker_opens_and_short_circuits():
    tool = _FakeTool(_raising)
    manager = ToolManager()
    # config/tool_runtime.yaml has no entry for this name -> falls back to
    # `default:` (failure_threshold=5) -- drive 5 failures to open the breaker.
    for _ in range(5):
        manager.call(tool, {}, tool_name="test.circuit_demo", timeout=1)
    assert manager.circuit_breaker.snapshot("test.circuit_demo")["state"] == OPEN

    calls_before = tool.calls
    result = manager.call(tool, {}, tool_name="test.circuit_demo", timeout=1)
    assert tool.calls == calls_before  # short-circuited, underlying tool not invoked
    assert result["status"] == "DEGRADED"


def test_plain_callable_without_invoke_is_supported():
    """Covers `XiaohongshuSearcher.search`-shaped tools: a plain bound
    method, not a LangChain `@tool` object."""

    def plain(keyword: str, limit: int = 10) -> Dict[str, Any]:
        return {"success": True, "keyword": keyword, "limit": limit}

    manager = ToolManager()
    result = manager.call(plain, {"keyword": "浮潜"}, tool_name="test.plain", timeout=1)
    assert result == {"success": True, "keyword": "浮潜", "limit": 10}


# -- Compatibility with existing `stub_external_calls` mocking strategy -------


def test_tool_manager_respects_stub_external_calls_monkeypatch(stub_external_calls):
    from travel_agent.tools.google_places import search_places

    manager = ToolManager()
    result = manager.call(
        search_places,
        {"query": "浅草寺", "place_type": "tourist_attraction", "limit": 3},
        tool_name="google_places.search_places",
    )
    assert isinstance(result, list)
    assert result and result[0]["success"] is True
    assert result[0]["name"] == "浅草寺"
