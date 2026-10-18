"""Parallel Retrieval (requirement doc section 11): dispatch all 5
retrievers concurrently, each isolated by `ToolManager`'s existing cache /
circuit-breaker / timeout pipeline (`tool_runtime/manager.py`) -- reused
as-is rather than hand-rolling a second timeout/fallback mechanism for RAG.

The rest of this codebase is synchronous end-to-end (`tool_runtime/manager.
py`'s own docstring: "there is no asyncio event loop running anywhere"), and
`ToolManager.call()` is itself a blocking call. `asyncio.gather` (asked for
explicitly by the requirement doc) is layered on top via
`asyncio.to_thread`, so each retriever's blocking `ToolManager.call()` still
runs concurrently on the existing thread-based path -- no second execution
model, just concurrency around the same blocking primitive.
`retrieve_all_sync()` is the entry point for callers in the still-synchronous
graph (`asyncio.run(...)` under the hood).
"""

from __future__ import annotations

import asyncio
import time
from typing import Callable, List, Optional, Tuple

from travel_agent.rag.retrievers import (
    dense_retriever,
    episodic_retriever,
    keyword_retriever,
    metadata_retriever,
    profile_retriever,
)
from travel_agent.rag.schemas import ParallelRetrievalResult, RetrievalContext, RetrievedChunk, SourceRetrievalStats
from travel_agent.tool_runtime.manager import get_tool_manager

_RETRIEVER_TOOLS: dict[str, Tuple[str, Callable[[RetrievalContext], List[RetrievedChunk]]]] = {
    "dense": ("rag.dense_retriever", dense_retriever.retrieve),
    "keyword": ("rag.keyword_retriever", keyword_retriever.retrieve),
    "metadata": ("rag.metadata_retriever", metadata_retriever.retrieve),
    "episodic": ("rag.episodic_retriever", episodic_retriever.retrieve),
    "profile": ("rag.profile_retriever", profile_retriever.retrieve),
}


def _call_one(
    source: str, tool_name: str, fn: Callable[[RetrievalContext], List[RetrievedChunk]], context: RetrievalContext
) -> Tuple[List[RetrievedChunk], float, Optional[str]]:
    start = time.perf_counter()
    result = get_tool_manager().call(fn, {"context": context}, tool_name=tool_name)
    elapsed_ms = (time.perf_counter() - start) * 1000

    if isinstance(result, dict) and result.get("success") is False:
        return [], elapsed_ms, result.get("error") or result.get("message") or f"{source} 检索失败"
    return (result or []), elapsed_ms, None


async def retrieve_all(context: RetrievalContext, sources: Optional[List[str]] = None) -> ParallelRetrievalResult:
    active = sources if sources is not None else list(_RETRIEVER_TOOLS)
    tasks = [asyncio.to_thread(_call_one, source, *_RETRIEVER_TOOLS[source], context) for source in active]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    chunks: List[RetrievedChunk] = []
    stats: List[SourceRetrievalStats] = []
    for source, outcome in zip(active, outcomes):
        if isinstance(outcome, BaseException):
            stats.append(SourceRetrievalStats(source=source, hit_count=0, latency_ms=0.0, error=str(outcome)))
            continue
        result_chunks, elapsed_ms, error = outcome
        chunks.extend(result_chunks)
        stats.append(SourceRetrievalStats(source=source, hit_count=len(result_chunks), latency_ms=elapsed_ms, error=error))

    return ParallelRetrievalResult(chunks=chunks, stats=stats)


def retrieve_all_sync(context: RetrievalContext, sources: Optional[List[str]] = None) -> ParallelRetrievalResult:
    """Synchronous entry point for the (still fully synchronous) graph."""
    return asyncio.run(retrieve_all(context, sources))
