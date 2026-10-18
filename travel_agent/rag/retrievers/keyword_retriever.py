"""Keyword-overlap retrieval over `travel_guides` (requirement doc section
11: "如果当前项目不方便引入完整 BM25，可先实现...关键词匹配补充；后续保留 BM25
接口"). No `rank_bm25`/`whoosh` dependency -- scores by counting
`keyword_queries`/`topic_filters` hits per document, which is enough to
surface exact-term matches the dense retriever's embedding similarity might
rank lower. `retrieve_bm25()` is the reserved seam: swap it in behind the
same `retrieve(context)` entry point once a real BM25 index exists, without
touching `parallel_retriever.py`.
"""

from __future__ import annotations

from typing import Any, Dict, List

from travel_agent.rag.chroma_client import get_collection
from travel_agent.rag.config import load_rag_config
from travel_agent.rag.retrievers.base import build_where_filter, chunk_from_row
from travel_agent.rag.schemas import RetrievalContext, RetrievedChunk


def _keyword_score(document: str, keyword_queries: List[str], topic_filters: List[str]) -> float:
    terms = [t for kq in keyword_queries for t in kq.split() if t] + list(topic_filters)
    if not terms:
        return 0.0
    hits = sum(1 for term in terms if term in document)
    return hits / len(terms)


def retrieve(context: RetrievalContext) -> List[RetrievedChunk]:
    config = load_rag_config()
    rewritten = context.rewritten
    if not rewritten.keyword_queries and not rewritten.topic_filters:
        return []

    collection = get_collection(config.collections.travel_guides)
    where = build_where_filter(rewritten.destination_filters, rewritten.topic_filters)
    rows: Dict[str, Any] = collection.get(where=where, include=["documents", "metadatas"])

    scored: List[RetrievedChunk] = []
    for chunk_id, document, metadata in zip(rows.get("ids", []), rows.get("documents", []), rows.get("metadatas", [])):
        score = _keyword_score(document, rewritten.keyword_queries, rewritten.topic_filters)
        if score <= 0:
            continue
        scored.append(chunk_from_row(chunk_id, document, metadata, retriever="keyword", keyword_score=score))

    scored.sort(key=lambda c: c.keyword_score or 0.0, reverse=True)
    return scored[: context.top_k]


def retrieve_bm25(context: RetrievalContext) -> List[RetrievedChunk]:
    """Reserved seam for a real BM25 index (requirement doc section 11).
    Not implemented -- no BM25 dependency is installed in this project yet."""
    raise NotImplementedError("BM25 retrieval is a reserved interface; use retrieve() for the keyword-overlap path")
