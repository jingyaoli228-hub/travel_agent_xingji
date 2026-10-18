"""User-profile retrieval (requirement doc section 11), wrapping
`ProfileMemory` L3 store (`memory/profile_memory.py`). Since Phase 4,
`ProfileMemory.get_statements()` returns one record *per preference
dimension* (with confidence/evidence_count/status) from the `user_profile`
ChromaDB collection -- so this retriever now returns one `RetrievedChunk`
per statement instead of one combined chunk per user, exactly as flagged
when this module was first written in Phase 3.
"""

from __future__ import annotations

from typing import List

from travel_agent.rag.config import load_rag_config
from travel_agent.rag.schemas import RetrievalContext, RetrievedChunk


def retrieve(context: RetrievalContext) -> List[RetrievedChunk]:
    if not context.user_id:
        return []

    from travel_agent.memory.profile_memory import ProfileMemory

    top_k = min(context.top_k, load_rag_config().retrieval.profile_top_k)
    statements = ProfileMemory().get_statements(context.user_id)[:top_k]

    return [
        RetrievedChunk(
            chunk_id=statement.profile_id,
            source_type="user_profile",
            retriever="profile",
            content=statement.statement,
            metadata={
                "user_id": context.user_id,
                "preference_dimension": statement.preference_dimension,
                "status": statement.status,
                "evidence_count": statement.evidence_count,
            },
            metadata_score=statement.confidence,
        )
        for statement in statements
    ]
