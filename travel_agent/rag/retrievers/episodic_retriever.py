"""Episodic-memory retrieval (requirement doc section 11), wrapping
`EpisodicMemory` L2 store (`memory/episodic_memory.py`). Since Phase 4,
`EpisodicMemory.retrieve_similar_trips()` tries real semantic search over
the `episodic_memory` ChromaDB collection first (via the `query_text` this
retriever now passes through) and falls back to JSONL + Jaccard tag-overlap
on any failure -- this retriever's own `retrieve(context)` contract did not
need to change across that upgrade, exactly as planned.
"""

from __future__ import annotations

from typing import List

from travel_agent.rag.config import load_rag_config
from travel_agent.rag.schemas import RetrievalContext, RetrievedChunk
from travel_agent.schemas.memory import TripEpisode


def _format_episode(episode: TripEpisode) -> str:
    parts = [f"目的地: {episode.destination}"] if episode.destination else []
    if episode.selected_experiences:
        names = [e.get("name", str(e)) for e in episode.selected_experiences]
        parts.append(f"选择过: {'、'.join(names)}")
    if episode.rejected_experiences:
        parts.append(f"拒绝过: {'、'.join(episode.rejected_experiences)}")
    if episode.feedback:
        parts.append(f"反馈: {'；'.join(episode.feedback)}")
    return "；".join(parts) or "（无详细记录）"


def retrieve(context: RetrievalContext) -> List[RetrievedChunk]:
    if not context.user_id:
        return []

    config = load_rag_config()
    rewritten = context.rewritten
    tags = list(set(rewritten.topic_filters) | set(rewritten.positive_preferences))
    top_k = min(context.top_k, config.retrieval.episodic_top_k)

    from travel_agent.memory.episodic_memory import EpisodicMemory

    episodes = EpisodicMemory().retrieve_similar_trips(
        context.user_id, tags, top_k=top_k, query_text=rewritten.semantic_query
    )

    chunks: List[RetrievedChunk] = []
    for idx, episode in enumerate(episodes):
        chunks.append(
            RetrievedChunk(
                chunk_id=f"episodic:{episode.session_id or context.user_id}:{idx}",
                source_type="episodic_memory",
                retriever="episodic",
                content=_format_episode(episode),
                metadata={"destination": episode.destination, "tags": episode.tags},
                metadata_score=1.0,
            )
        )
    return chunks
