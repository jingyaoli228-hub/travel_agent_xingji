"""LLM Rerank (requirement doc section 14): judge each merged candidate on
relevance/personalization/actionability/freshness/duplication/staleness,
keep only the genuinely useful ones -- "不要把全部召回内容直接塞进 Prompt".

Dual-path, same convention as the rest of `rag/`: LLM structured output when
a client is given, heuristic (top `rerank_top_k` by fusion score) otherwise.
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field

from travel_agent.rag.config import load_rag_config
from travel_agent.rag.schemas import RerankedChunk, RetrievedChunk
from travel_agent.utils.logging import get_logger

_logger = get_logger("travel_agent.rag.reranker")


class _RerankBatch(BaseModel):
    items: List[RerankedChunk] = Field(default_factory=list)


def _heuristic_rerank(candidates: List[RetrievedChunk], rerank_top_k: int) -> List[RerankedChunk]:
    ordered = sorted(candidates, key=lambda c: c.combined_score, reverse=True)
    reranked = []
    for i, chunk in enumerate(ordered):
        reranked.append(
            RerankedChunk(
                chunk_id=chunk.chunk_id,
                relevance_score=chunk.combined_score,
                personalization_score=0.0,
                actionability_score=0.0,
                freshness_score=chunk.freshness_score or 0.0,
                reason="按融合分数排序（无 LLM 重排）",
                selected=i < rerank_top_k,
            )
        )
    return reranked


def rerank(
    user_query: str,
    candidates: List[RetrievedChunk],
    rewritten_query: Optional[Any] = None,
    user_profile: Optional[Any] = None,
    travel_requirement: Optional[Any] = None,
    current_plan: Optional[Any] = None,
    llm: Optional[Any] = None,
) -> List[RerankedChunk]:
    if not candidates:
        return []

    rerank_top_k = load_rag_config().retrieval.rerank_top_k
    if llm is not None:
        reranked = _rerank_with_llm(
            user_query, candidates, rewritten_query, user_profile, travel_requirement, current_plan, llm, rerank_top_k
        )
        if reranked is not None:
            return reranked
    return _heuristic_rerank(candidates, rerank_top_k)


def _rerank_with_llm(
    user_query: str,
    candidates: List[RetrievedChunk],
    rewritten_query: Optional[Any],
    user_profile: Optional[Any],
    travel_requirement: Optional[Any],
    current_plan: Optional[Any],
    llm: Any,
    rerank_top_k: int,
) -> Optional[List[RerankedChunk]]:
    try:
        structured_llm = llm.with_structured_output(_RerankBatch, method="function_calling")

        def _dump(obj: Any) -> str:
            if obj is None:
                return "无"
            return str(obj.model_dump()) if hasattr(obj, "model_dump") else str(obj)

        candidate_lines = "\n".join(
            f"- chunk_id={c.chunk_id} | 来源={c.source_type} | 融合分={c.combined_score:.2f}\n  内容: {c.content[:300]}"
            for c in candidates
        )
        prompt = (
            "请对以下候选内容逐条判断：1)是否直接回答用户需求 2)是否与目的地匹配 "
            "3)是否符合用户偏好 4)是否支持当前规划动作 5)是否具体可执行 6)是否与其他候选重复 "
            "7)是否可能过时 8)是否只是泛化描述。\n"
            f"为每条候选给出 relevance_score/personalization_score/actionability_score/"
            f"freshness_score（0-1）、reason（具体原因）、selected（是否保留，最多保留 {rerank_top_k} 条最相关的）。\n"
            f"chunk_id 必须原样复制候选中的 chunk_id，不要编造或修改。\n\n"
            f"用户原始请求: {user_query}\n"
            f"改写后的查询: {_dump(rewritten_query)}\n"
            f"用户画像: {_dump(user_profile)}\n"
            f"旅行需求: {_dump(travel_requirement)}\n"
            f"当前行程: {_dump(current_plan)}\n\n"
            f"候选列表:\n{candidate_lines}\n"
        )
        result = structured_llm.invoke([("human", prompt)])
        if not isinstance(result, _RerankBatch) or not result.items:
            return None

        known_ids = {c.chunk_id for c in candidates}
        valid_items = [item for item in result.items if item.chunk_id in known_ids]
        if not valid_items:
            return None
        selected_count = sum(1 for item in valid_items if item.selected)
        if selected_count > rerank_top_k:
            # LLM over-selected -- keep only the top `rerank_top_k` by relevance among selected ones.
            selected_sorted = sorted((i for i in valid_items if i.selected), key=lambda i: i.relevance_score, reverse=True)
            keep_ids = {i.chunk_id for i in selected_sorted[:rerank_top_k]}
            for item in valid_items:
                if item.selected and item.chunk_id not in keep_ids:
                    item.selected = False
        return valid_items
    except Exception as exc:  # noqa: BLE001 -- fall back to heuristic, never raise
        _logger.warning("reranker LLM path failed, using heuristic: %s", exc)
        return None
