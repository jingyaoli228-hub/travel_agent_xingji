"""Step 6: write `TravelGuideChunk`s into the `travel_guides` ChromaDB
collection.

Dedup/version management (requirement doc section 6/12) comes for free from
chunk IDs being deterministic: `TravelGuideChunk.id` is
`f"{source_file}#{note_index}::{chunk_index}"`, so re-ingesting the same file
re-derives the same IDs and `collection.upsert()` overwrites in place rather
than duplicating. `write_chunks()` still checks which IDs already existed
*before* the upsert purely to report `chunks_written` vs `chunks_updated`
accurately in `IngestionReport`.

Chroma metadata values must be scalars (no nested lists/dicts) -- list
fields (`activity_topics`, `travel_styles`, `suitable_for`, `unsuitable_for`,
`aliases`) are flattened to `"|"`-joined strings for `where=` filtering, and
the full structured chunk is also stored as a JSON string under
`_chunk_json` so a retriever can reconstruct an exact `TravelGuideChunk`
without re-deriving it from the flattened fields.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from travel_agent.rag.chroma_client import get_collection
from travel_agent.rag.config import load_rag_config
from travel_agent.rag.schemas import TravelGuideChunk


def _to_chroma_metadata(chunk: TravelGuideChunk) -> Dict[str, Any]:
    return {
        "destination_country": chunk.destination_country or "",
        "destination_city": chunk.destination_city or "",
        "destination_region": chunk.destination_region or "",
        "canonical_destination": chunk.canonical_destination or "",
        "canonical_region": chunk.canonical_region or "",
        "canonical_place_name": chunk.canonical_place_name or "",
        "guide_type": chunk.guide_type or "",
        "source_type": chunk.source_type or "",
        "source_title": chunk.source_title or "",
        "publish_time": chunk.publish_time or "",
        "collected_time": chunk.collected_time or "",
        "freshness_level": chunk.freshness_level or "",
        "quality_score": chunk.quality_score if chunk.quality_score is not None else 0.0,
        "parent_document_id": chunk.parent_document_id,
        "chunk_index": chunk.chunk_index,
        "activity_topics": "|".join(chunk.activity_topics),
        "travel_styles": "|".join(chunk.travel_styles),
        "suitable_for": "|".join(chunk.suitable_for),
        "unsuitable_for": "|".join(chunk.unsuitable_for),
        "aliases": "|".join(chunk.aliases),
        "_chunk_json": chunk.model_dump_json(),
    }


def write_chunks(chunks: List[TravelGuideChunk]) -> Tuple[int, int]:
    """Upsert `chunks` into `travel_guides`. Returns `(written, updated)`."""
    if not chunks:
        return 0, 0

    config = load_rag_config()
    collection = get_collection(config.collections.travel_guides)

    ids = [c.id for c in chunks]
    existing = collection.get(ids=ids)
    existing_ids = set(existing.get("ids") or [])

    collection.upsert(
        ids=ids,
        documents=[c.content for c in chunks],
        metadatas=[_to_chroma_metadata(c) for c in chunks],
    )

    updated = sum(1 for i in ids if i in existing_ids)
    written = len(ids) - updated
    return written, updated
