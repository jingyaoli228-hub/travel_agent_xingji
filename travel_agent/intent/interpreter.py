"""`MultiSignalIntentInterpreter` -- the unified entry point every user
message is meant to pass through (design doc section II/V/VI).

Fast Path: Pattern + Workflow State only, no network call. Escalates to the
Deep Path whenever the complexity classifier flags it OR the Fast Path's own
confidence gate fails (see `fusion_resolver.build_fast_result`).

Deep Path: Pattern (in-process, instant) + Embedding + LLM. The design doc's
reference implementation fans these out via `asyncio.gather`; this codebase
is 100% synchronous (LangGraph nodes, LangChain `.invoke()`), so the same
"run in parallel, cap each branch's wait, isolate its failures" behavior is
implemented with a `ThreadPoolExecutor` instead -- functionally equivalent
for I/O-bound calls, without requiring every sync node to wrap `asyncio.run()`.
A soft per-branch timeout is enforced via `future.result(timeout=...)`; the
executor is *not* used as a context manager so a slow LLM call doesn't block
the whole request past its timeout waiting for `shutdown(wait=True)`.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, TypeVar

from travel_agent.intent.complexity_classifier import RequestComplexityClassifier
from travel_agent.intent.config import load_fusion_config
from travel_agent.intent.embedding_router import EmbeddingIntentRetriever
from travel_agent.intent.fusion_resolver import FusionResolver, build_fast_result
from travel_agent.intent.llm_resolver import LLMIntentResolver
from travel_agent.intent.pattern_parser import PatternParser
from travel_agent.intent.schemas import EmbeddingIntentResult, IntentContext, IntentResult
from travel_agent.utils.logging import get_logger

_logger = get_logger("travel_agent.intent.interpreter")

T = TypeVar("T")


class MultiSignalIntentInterpreter:
    def __init__(self) -> None:
        self._complexity_classifier = RequestComplexityClassifier()
        self._pattern_parser = PatternParser()
        self._embedding_retriever = EmbeddingIntentRetriever()
        self._llm_resolver = LLMIntentResolver()
        self._fusion_resolver = FusionResolver()

    def interpret(self, message: str, context: IntentContext) -> IntentResult:
        pattern = self._pattern_parser.parse(message, context)
        complexity = asyncio.run(self._complexity_classifier.classify(message, context))

        if complexity.level == "SIMPLE":
            fast_result = build_fast_result(pattern, context)
            if fast_result is not None:
                fast_result.evidence["complexity"] = complexity.model_dump()
                return fast_result
            _logger.info("Fast Path declined (low confidence or invalid), escalating to Deep Path: %r", message)

        return self._deep_recognize(message, context, pattern, complexity)

    def _deep_recognize(self, message, context: IntentContext, pattern, complexity) -> IntentResult:
        cfg = load_fusion_config().timeouts
        executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="intent-deep-path")
        try:
            embedding_future = executor.submit(self._embedding_retriever.retrieve, message, context)
            llm_future = executor.submit(self._llm_resolver.resolve, message, context, pattern, None)

            embedding_result = self._wait(embedding_future, cfg.embedding_seconds, EmbeddingIntentResult(), "embedding")
            llm_result = self._wait(llm_future, cfg.llm_seconds, None, "llm")
        finally:
            # Don't block returning to the caller on a slow branch that
            # already missed its own timeout -- let it finish in the
            # background instead of joining it here.
            executor.shutdown(wait=False)

        result = self._fusion_resolver.fuse(message, context, pattern, embedding_result, llm_result)
        result.evidence["complexity"] = complexity.model_dump()
        return result

    @staticmethod
    def _wait(future, timeout: float, default: T, branch_name: str) -> T:
        try:
            return future.result(timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - one branch failing must not fail the whole request
            _logger.warning("Deep Path branch %r failed/timed out: %s", branch_name, exc)
            return default
