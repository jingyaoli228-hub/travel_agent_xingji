"""Per-tool CLOSED / OPEN / HALF_OPEN circuit breaker.

Hand-rolled (no `pybreaker`/`tenacity` -- neither is installed, and this is
~60 lines of stdlib-only logic, matching the project's existing minimal-deps
style). One instance is shared process-wide via `ToolManager`, state keyed by
`tool_name`.

CLOSED -> (>= failure_threshold consecutive failures) -> OPEN
OPEN -> (cooldown_seconds elapsed) -> HALF_OPEN (one trial call allowed)
HALF_OPEN -> (trial succeeds) -> CLOSED
HALF_OPEN -> (trial fails) -> OPEN (cooldown restarts)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict

CLOSED = "CLOSED"
OPEN = "OPEN"
HALF_OPEN = "HALF_OPEN"


@dataclass
class _ToolBreakerState:
    state: str = CLOSED
    consecutive_failures: int = 0
    opened_at: float = 0.0
    total_failures: int = 0
    total_successes: int = 0


class CircuitBreaker:
    def __init__(self) -> None:
        self._states: Dict[str, _ToolBreakerState] = {}

    def _get(self, tool_name: str) -> _ToolBreakerState:
        return self._states.setdefault(tool_name, _ToolBreakerState())

    def allow(self, tool_name: str, failure_threshold: int, cooldown_seconds: float) -> bool:
        """Whether a call to `tool_name` should proceed right now."""
        st = self._get(tool_name)
        if st.state == OPEN:
            if time.time() - st.opened_at >= cooldown_seconds:
                st.state = HALF_OPEN
                return True
            return False
        return True

    def record_success(self, tool_name: str) -> None:
        st = self._get(tool_name)
        st.state = CLOSED
        st.consecutive_failures = 0
        st.total_successes += 1

    def record_failure(self, tool_name: str, failure_threshold: int) -> None:
        st = self._get(tool_name)
        st.consecutive_failures += 1
        st.total_failures += 1
        if st.state == HALF_OPEN or st.consecutive_failures >= failure_threshold:
            st.state = OPEN
            st.opened_at = time.time()

    def snapshot(self, tool_name: str) -> Dict[str, object]:
        st = self._get(tool_name)
        return {
            "state": st.state,
            "consecutive_failures": st.consecutive_failures,
            "total_failures": st.total_failures,
            "total_successes": st.total_successes,
        }

    def reset(self) -> None:
        self._states.clear()
