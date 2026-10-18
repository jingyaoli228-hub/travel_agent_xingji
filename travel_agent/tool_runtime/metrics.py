"""In-process per-tool call metrics: success rate, avg/p95 latency, timeout
rate, cache-hit count, fallback count -- feeds a future Monitor/debug
endpoint (`snapshot()` is import-and-call-ready; no exposition endpoint is
wired up yet since none exists in this codebase today).

No `prometheus_client` dependency: nothing in the repo currently exposes a
`/metrics` endpoint to plug into, so a stdlib in-process counter store is the
right amount of infrastructure for now.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class _ToolMetrics:
    calls: int = 0
    errors: int = 0
    timeouts: int = 0
    cache_hits: int = 0
    fallbacks: int = 0
    validation_errors: int = 0
    latencies_ms: List[float] = field(default_factory=list)


def _percentile(sorted_values: List[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(len(sorted_values) * pct))
    return sorted_values[idx]


class MetricsRegistry:
    def __init__(self) -> None:
        self._metrics: Dict[str, _ToolMetrics] = {}

    def _get(self, tool_name: str) -> _ToolMetrics:
        return self._metrics.setdefault(tool_name, _ToolMetrics())

    def record_call(self, tool_name: str, latency_ms: float, success: bool) -> None:
        m = self._get(tool_name)
        m.calls += 1
        m.latencies_ms.append(latency_ms)
        if not success:
            m.errors += 1

    def record_timeout(self, tool_name: str, latency_ms: float) -> None:
        m = self._get(tool_name)
        m.calls += 1
        m.timeouts += 1
        m.errors += 1
        m.latencies_ms.append(latency_ms)

    def record_cache_hit(self, tool_name: str) -> None:
        self._get(tool_name).cache_hits += 1

    def record_fallback(self, tool_name: str) -> None:
        self._get(tool_name).fallbacks += 1

    def record_validation_error(self, tool_name: str) -> None:
        self._get(tool_name).validation_errors += 1

    def snapshot(self, tool_name: Optional[str] = None) -> Dict[str, object]:
        def _one(m: _ToolMetrics) -> Dict[str, object]:
            lat = sorted(m.latencies_ms)
            return {
                "calls_total": m.calls,
                "errors_total": m.errors,
                "timeouts_total": m.timeouts,
                "cache_hits_total": m.cache_hits,
                "fallbacks_total": m.fallbacks,
                "validation_errors_total": m.validation_errors,
                "success_rate": ((m.calls - m.errors) / m.calls) if m.calls else None,
                "avg_latency_ms": statistics.mean(lat) if lat else 0.0,
                "p95_latency_ms": _percentile(lat, 0.95),
                "timeout_rate": (m.timeouts / m.calls) if m.calls else None,
            }

        if tool_name is not None:
            return _one(self._get(tool_name))
        return {name: _one(m) for name, m in self._metrics.items()}

    def reset(self) -> None:
        self._metrics.clear()
