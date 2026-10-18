"""`ToolManager.call()` -- the single entry point every agent must use to
call a tool (LangChain `@tool` object, or a plain instance-method callable
like `XiaohongshuSearcher.search`). Agents are not allowed to call
`.invoke()`/tool functions directly; see `agents/research_agent.py`,
`agents/planner_agent.py`, `graph/nodes.py` for call sites.

Pipeline, in order:
    1. Cache check
    2. Circuit breaker check
    3. JSON Schema (pydantic) parameter validation
    4. Timeout-wrapped execution (thread-based, see module docstring below)
    5. Execute tool
    6. Update metrics + circuit breaker
    7. Fallback handler

Timeout note: the whole codebase (tools, agents, LangGraph nodes) is
synchronous -- there is no `asyncio` event loop running anywhere. Rather than
invent the codebase's first async boundary, this uses the same
`ThreadPoolExecutor` + `future.result(timeout=...)` idiom already
established by `travel_agent/intent/interpreter.py::_deep_recognize()`: the
executor is not used as a context manager (so a slow call doesn't block
`shutdown(wait=True)`), it's shut down with `wait=False` and left to finish
in the background after a timeout fires.

Contract preservation: every tool already returns a normalized
`{"success": bool, ...}` dict (or a list of such dicts) and never raises --
`ToolManager.call()` returns that exact same shape on success. On failure
(timeout, exception, circuit open, invalid params, or the tool's own
`success: False`) it returns a same-shaped degraded/invalid-parameter dict
(or calls `fallback()` if one was given), so callers written against the old
direct-`.invoke()` contract keep working unmodified.
"""

from __future__ import annotations

import concurrent.futures as cf
import time
from typing import Any, Callable, Dict, Optional

from pydantic import ValidationError

from travel_agent.tool_runtime.cache import CacheStore
from travel_agent.tool_runtime.circuit_breaker import CircuitBreaker
from travel_agent.tool_runtime.config import load_tool_runtime_config
from travel_agent.tool_runtime.metrics import MetricsRegistry
from travel_agent.tool_runtime.registry import get_tool_spec
from travel_agent.utils.logging import get_logger

_logger = get_logger("travel_agent.tool_runtime")


def _is_success(result: Any) -> bool:
    if isinstance(result, list):
        if result and isinstance(result[0], dict) and result[0].get("success") is False:
            return False
        return True
    if isinstance(result, dict):
        return result.get("success") is not False
    return True


def _shaped(payload: Dict[str, Any], as_list: bool) -> Any:
    return [payload] if as_list else payload


def _degraded(tool_name: str, message: str, as_list: bool) -> Any:
    return _shaped({"success": False, "status": "DEGRADED", "error": message}, as_list)


def _invalid_params(message: str, as_list: bool) -> Any:
    return _shaped({"success": False, "status": "INVALID_PARAMETER", "message": message}, as_list)


class ToolManager:
    def __init__(self) -> None:
        self._cache = CacheStore()
        self._breaker = CircuitBreaker()
        self._metrics = MetricsRegistry()

    @property
    def metrics(self) -> MetricsRegistry:
        return self._metrics

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        return self._breaker

    @property
    def cache(self) -> CacheStore:
        return self._cache

    def call(
        self,
        tool: Any,
        kwargs: Dict[str, Any],
        *,
        tool_name: str,
        timeout: Optional[float] = None,
        cache_ttl: Optional[float] = None,
        fallback: Optional[Callable[[], Any]] = None,
    ) -> Any:
        spec = get_tool_spec(tool_name)
        tool_cfg = load_tool_runtime_config().for_tool(tool_name)
        effective_timeout = timeout if timeout is not None else tool_cfg.timeout_seconds
        effective_cache_ttl = cache_ttl if cache_ttl is not None else tool_cfg.cache_ttl_seconds
        as_list = spec.result_is_list
        kwargs = kwargs or {}

        # 1. Cache check
        if effective_cache_ttl > 0:
            cached = self._cache.get(tool_name, kwargs)
            if cached is not None:
                self._metrics.record_cache_hit(tool_name)
                return cached

        # 2. Circuit breaker check
        breaker_cfg = tool_cfg.circuit_breaker
        if not self._breaker.allow(tool_name, breaker_cfg.failure_threshold, breaker_cfg.cooldown_seconds):
            _logger.warning("tool_runtime circuit OPEN for %s, skipping call", tool_name)
            if fallback is not None:
                self._metrics.record_fallback(tool_name)
                return fallback()
            return _degraded(tool_name, f"{tool_name} 熔断中，暂时不可用", as_list)

        # 3. JSON Schema (pydantic) parameter validation
        args_schema = getattr(tool, "args_schema", None) or spec.args_schema
        if args_schema is not None:
            try:
                args_schema.model_validate(kwargs)
            except ValidationError as exc:
                self._metrics.record_validation_error(tool_name)
                return _invalid_params(str(exc), as_list)

        # 4-5. Timeout-wrapped execution
        has_invoke = hasattr(tool, "invoke") and callable(getattr(tool, "invoke"))
        start = time.perf_counter()
        executor = cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"tool-{tool_name}")
        try:
            if has_invoke:
                future = executor.submit(tool.invoke, kwargs)
            else:
                future = executor.submit(lambda: tool(**kwargs))
            result = future.result(timeout=effective_timeout)
        except cf.TimeoutError:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_timeout(tool_name, elapsed_ms)
            self._breaker.record_failure(tool_name, breaker_cfg.failure_threshold)
            _logger.warning("tool_runtime timeout for %s after %.0fms", tool_name, elapsed_ms)
            if fallback is not None:
                self._metrics.record_fallback(tool_name)
                return fallback()
            return _degraded(tool_name, f"{tool_name} 调用超时 (>{effective_timeout}s)", as_list)
        except Exception as exc:  # noqa: BLE001 - tools must never crash the caller
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._metrics.record_call(tool_name, elapsed_ms, success=False)
            self._breaker.record_failure(tool_name, breaker_cfg.failure_threshold)
            _logger.error("tool_runtime error for %s: %s", tool_name, exc)
            if fallback is not None:
                self._metrics.record_fallback(tool_name)
                return fallback()
            return _degraded(tool_name, str(exc), as_list)
        finally:
            # Not a context manager: a call that already missed its timeout
            # shouldn't also block here waiting for the thread to join.
            executor.shutdown(wait=False)

        # 6. Update metrics + circuit breaker based on business-level success
        elapsed_ms = (time.perf_counter() - start) * 1000
        success = _is_success(result)
        self._metrics.record_call(tool_name, elapsed_ms, success=success)
        if success:
            self._breaker.record_success(tool_name)
            if effective_cache_ttl > 0:
                self._cache.set(tool_name, kwargs, result, effective_cache_ttl)
            return result

        self._breaker.record_failure(tool_name, breaker_cfg.failure_threshold)

        # 7. Fallback handler (tool itself returned success: False)
        if fallback is not None:
            self._metrics.record_fallback(tool_name)
            fallback_result = fallback()
            if fallback_result is not None:
                return fallback_result
        return result


_tool_manager: Optional[ToolManager] = None


def get_tool_manager() -> ToolManager:
    global _tool_manager
    if _tool_manager is None:
        _tool_manager = ToolManager()
    return _tool_manager
