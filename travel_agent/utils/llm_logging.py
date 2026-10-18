"""LLM call latency/token logging.

`LatencyLoggingHandler` is a LangChain callback handler attached to every
chat model `get_llm()` builds, so every agent gets `[LLM] <Agent> <Model>
<latency>s` logging for free without any call site changes. Token counts are
best-effort (pulled from `response.llm_output`/`usage_metadata` when the
provider reports them) since not every OpenAI-compatible backend does.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from travel_agent.utils.logging import get_logger

_logger = get_logger("travel_agent.llm")

_ROLE_LABEL_CN = {
    "requirement": "Requirement Agent",
    "research": "Research Orchestrator",
    "planner": "Planner Agent",
    "reviewer": "Reviewer Agent",
    "intent": "Intent Resolver",
}


class LatencyLoggingHandler(BaseCallbackHandler):
    """Logs `[LLM] <role label> <model> <latency>s (in=X out=Y tokens)`."""

    def __init__(self, role: Optional[str], tier: Optional[str], model: str) -> None:
        self._label = _ROLE_LABEL_CN.get(role or "", role or "LLM")
        self._tier = tier or ""
        self._model = model
        self._starts: Dict[UUID, float] = {}

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], *, run_id: UUID, **kwargs: Any) -> None:
        self._starts[run_id] = time.perf_counter()

    def on_chat_model_start(self, serialized: Dict[str, Any], messages: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._starts[run_id] = time.perf_counter()

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        started = self._starts.pop(run_id, None)
        latency_s = (time.perf_counter() - started) if started is not None else float("nan")
        tokens_in, tokens_out = self._extract_tokens(response)
        token_part = f" (in={tokens_in} out={tokens_out} tokens)" if tokens_in is not None else ""
        _logger.info("[LLM] %s %s %.1fs%s", self._label, self._model, latency_s, token_part)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        started = self._starts.pop(run_id, None)
        latency_s = (time.perf_counter() - started) if started is not None else float("nan")
        _logger.warning("[LLM] %s %s FAILED after %.1fs: %s", self._label, self._model, latency_s, error)

    @staticmethod
    def _extract_tokens(response: Any) -> tuple[Optional[int], Optional[int]]:
        try:
            usage = (response.llm_output or {}).get("token_usage") or {}
            if usage:
                return usage.get("prompt_tokens"), usage.get("completion_tokens")
            for gen_list in response.generations or []:
                for gen in gen_list:
                    meta = getattr(getattr(gen, "message", None), "usage_metadata", None)
                    if meta:
                        return meta.get("input_tokens"), meta.get("output_tokens")
        except Exception:  # noqa: BLE001 - logging must never break the LLM call
            pass
        return None, None
