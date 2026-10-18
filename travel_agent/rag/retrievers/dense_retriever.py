"""Dense vector retrieval over the `travel_guides` collection (requirement
doc section 11/12): `RewrittenQuery.semantic_query` -> Chroma `.query()`,
filtered by `destination_filters` when present.

Distance -> score: `1 / (1 + distance)`, monotonic and bounded in (0, 1]
without assuming a fixed max distance for whichever space the embedding
function uses (spec section 12: "不将距离直接视为概率"). `retrieval.
distance_threshold` is *not* applied as a hard cutoff here -- with no
calibrated eval data yet (Phase 7 adds `scripts/eval_rag_retrieval.py`), a
premature hard threshold risks silently dropping valid results. Every
candidate this retriever returns is scored, not filtered; `result_merger.py`/
`reranker.py` make the actual relevance call downstream.
"""

from __future__ import annotations

from typing import List

from travel_agent.rag.chroma_client import get_collection
from travel_agent.rag.config import load_rag_config
from travel_agent.rag.retrievers.base import build_where_filter, chunk_from_row
from travel_agent.rag.schemas import RetrievalContext, RetrievedChunk


def retrieve(context: RetrievalContext) -> List[RetrievedChunk]:
    config = load_rag_config()
    rewritten = context.rewritten
    if not rewritten.semantic_query.strip():
        return []

    collection = get_collection(config.collections.travel_guides)
    where = build_where_filter(rewritten.destination_filters, rewritten.topic_filters)
    top_k = min(context.top_k, config.retrieval.dense_top_k)

    result = collection.query(
        query_texts=[rewritten.semantic_query],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    ids = (result.get("ids") or [[]])[0]
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    chunks: List[RetrievedChunk] = []
    for chunk_id, document, metadata, distance in zip(ids, documents, metadatas, distances):
        score = 1.0 / (1.0 + max(distance, 0.0))
        chunks.append(chunk_from_row(chunk_id, document, metadata, retriever="dense", dense_score=score))
    return chunks
