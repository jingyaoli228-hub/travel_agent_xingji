"""Production-grade tool-calling middleware: every external tool call (Google
Places/Routes/Weather, Agent Reach, Xiaohongshu) is routed through
`ToolManager.call()` instead of being invoked directly by agent code.

Pipeline (see `manager.py::ToolManager.call`): cache check -> circuit breaker
check -> JSON-schema (pydantic) parameter validation -> timeout-wrapped
execution -> metrics update -> fallback handling. Agents never construct an
LLM client directly (see `config/llm.py`); the same rule now applies to tool
calls, via `get_tool_manager()`.
"""

from __future__ import annotations

from travel_agent.tool_runtime.manager import ToolManager, get_tool_manager

__all__ = ["ToolManager", "get_tool_manager"]
