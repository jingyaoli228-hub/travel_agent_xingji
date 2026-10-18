"""Pure metadata-filter retrieval over `travel_guides` (requirement doc
section 11): no ranking, just "does this chunk's destination/region/topic
match what the rewritten query asked for". Every match gets the same
`metadata_score=1.0` -- this retriever's job is recall of exact-filter
matches the dense/keyword retrievers might rank low, not relevance ordering.
"""

from __future__ import annotations

from typing import List

from travel_agent.rag.chroma_client import get_collection
from travel_agent.rag.config import load_rag_config
from travel_agent.rag.retrievers.base import build_where_filter, chunk_from_row, topic_overlap
from travel_agent.rag.schemas import RetrievalContext, RetrievedChunk


def retrieve(context: RetrievalContext) -> List[RetrievedChunk]:
    config = load_rag_config()
    rewritten = context.rewritten
    where = build_where_filter(rewritten.destination_filters, rewritten.topic_filters)
    if where is None and not rewritten.topic_filters:
        return []  # nothing to filter on -- not this retriever's job to return everything

    collection = get_collection(config.collections.travel_guides)
    rows = collection.get(where=where, include=["documents", "metadatas"])

    chunks: List[RetrievedChunk] = []
    for chunk_id, document, metadata in zip(rows.get("ids", []), rows.get("documents", []), rows.get("metadatas", [])):
        if not topic_overlap(metadata, rewritten.topic_filters):
            continue
        chunks.append(chunk_from_row(chunk_id, document, metadata, retriever="metadata", metadata_score=1.0))
    return chunks[: context.top_k]
