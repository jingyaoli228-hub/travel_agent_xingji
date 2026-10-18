"""LLM intent resolver (design doc section 9): the highest-weighted signal
in the Deep Path fusion, but never trusted blind -- `fusion_resolver.py`
recomputes confidence from workflow validity/agreement/ambiguity rather than
using the LLM's self-reported score directly. Returns `None` on any failure
(no key configured, malformed output, network error) so the caller can fall
back to Pattern + Embedding alone -- one failed signal never fails the whole
request.
"""

from __future__ import annotations

from typing import Optional

from travel_agent.config.llm import get_llm
from travel_agent.intent.schemas import EmbeddingIntentResult, IntentContext, IntentResult, PatternResult
from travel_agent.prompts_loader import load_prompt
from travel_agent.utils.logging import get_logger

_logger = get_logger("travel_agent.intent.llm_resolver")


class LLMIntentResolver:
    def __init__(self) -> None:
        # tier="fast": resolves via with_structured_output, which deepseek-reasoner
        # (the "deep" tier) cannot do (no tool-calling support).
        self._llm = get_llm(role="intent", tier="fast")
        self._system_prompt = load_prompt("intent_llm_resolver")

    def resolve(
        self,
        message: str,
        context: IntentContext,
        pattern: PatternResult,
        embedding: Optional[EmbeddingIntentResult] = None,
    ) -> Optional[IntentResult]:
        if self._llm is None:
            return None
        try:
            # method="function_calling": see requirement_agent.py's identical
            # comment -- DeepSeek rejects the response_format=json_schema
            # default for pydantic targets.
            structured_llm = self._llm.with_structured_output(IntentResult, method="function_calling")
            messages = []
            if self._system_prompt:
                messages.append(("system", self._system_prompt))
            messages.append(("human", self._build_prompt(message, context, pattern, embedding)))
            result = structured_llm.invoke(messages)
            if isinstance(result, IntentResult):
                return result
        except Exception as exc:  # noqa: BLE001 - any failure falls back to Pattern+Embedding only
            _logger.warning("LLM intent resolution failed: %s", exc)
        return None

    def _build_prompt(
        self,
        message: str,
        context: IntentContext,
        pattern: PatternResult,
        embedding: Optional[EmbeddingIntentResult],
    ) -> str:
        embedding = embedding or EmbeddingIntentResult()
        return (
            "请解析用户最新消息的意图，输出结构化 IntentResult。\n\n"
            f"用户消息: {message}\n\n"
            f"会话上下文: {context.model_dump_json()}\n\n"
            f"规则解析候选(Pattern): {pattern.model_dump_json()}\n\n"
            f"向量检索候选(Embedding): {embedding.model_dump_json()}\n\n"
            "next_agents 只能从 ['RequirementAgent','ResearchOrchestrator','PlannerAgent','PresentationAgent'] 中选择。"
        )
