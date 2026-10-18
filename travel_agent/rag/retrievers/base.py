"""Shared helpers for the `travel_guides`-backed retrievers (dense/keyword/
metadata). Not used by `episodic_retriever.py`/`profile_retriever.py`, which
read different stores entirely.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from travel_agent.rag.schemas import RetrievedChunk


def chunk_from_row(
    chunk_id: str,
    document: str,
    metadata: Dict[str, Any],
    retriever: str,
    dense_score: Optional[float] = None,
    keyword_score: Optional[float] = None,
    metadata_score: Optional[float] = None,
) -> RetrievedChunk:
    """Build a `RetrievedChunk` from one row of a `travel_guides` Chroma
    result (`ids`/`documents`/`metadatas`). `metadata` is the flattened
    Chroma metadata dict written by `embedding_writer._to_chroma_metadata` --
    `_chunk_json` (if present) carries the full structured `TravelGuideChunk`
    for richer downstream use (context assembly), but retrievers only need
    the flattened scalar fields for scoring/filtering."""
    quality_score = metadata.get("quality_score")
    freshness_level = metadata.get("freshness_level") or ""
    freshness_score = {"fresh": 1.0, "recent": 0.6, "outdated": 0.2}.get(freshness_level, 0.5)

    return RetrievedChunk(
        chunk_id=chunk_id,
        source_type="travel_guide",
        retriever=retriever,
        content=document,
        metadata=metadata,
        dense_score=dense_score,
        keyword_score=keyword_score,
        metadata_score=metadata_score,
        source_quality_score=float(quality_score) if quality_score is not None else None,
        freshness_score=freshness_score,
    )


def parse_chunk_json(metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    raw = metadata.get("_chunk_json")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def build_where_filter(destination_filters: Dict[str, Any], topic_filters: List[str]) -> Optional[Dict[str, Any]]:
    """Translate `RewrittenQuery.destination_filters`/`topic_filters` into a
    Chroma `where=` clause. Only `destination` (matched against
    `canonical_destination` OR `destination_city`) is filtered this way --
    `activity_topics`/`travel_styles` are `"|"`-joined strings in Chroma
    metadata (substring match isn't expressible in `where=`), so topic
    filtering happens as a post-filter in the retriever instead.

    Confirmed live bug this fixes: `destination_intelligence/service.py`'s
    known-region table names Bali's regions in English ("Ubud"/"Canggu"/
    "Seminyak"/"Nusa Penida" -- that's what ends up in
    `req.region_preferences`, and what callers like `research_agent.py::
    _discover_specialties` pass in here), while `rag/ingestion/
    canonicalization.py` normalizes ingested guide notes to their Chinese
    canonical names ("乌布"/"苍古"/"水明漾"/"佩尼达岛" -- matching what the
    user's actual Xiaohongshu notes say). An exact-string `where=` match
    against the raw caller-supplied value silently matched zero rows for
    every real Bali region name -- RAG discovery looked like it "did
    nothing" even with correctly ingested, on-topic data sitting right
    there. Canonicalizing the filter value here (same alias table
    ingestion already uses) makes the match resilient to either language/
    casing, whichever a caller happens to pass."""
    destination = destination_filters.get("destination")
    if not destination:
        return None

    from travel_agent.rag.ingestion.canonicalization import canonicalize

    canon = canonicalize(destination)
    values = {destination}

    if canon.get("canonical_region"):
        # Resolves to a specific sub-region (e.g. "Ubud" -> "乌布") -- stay
        # region-scoped. Matching the broader canonical_destination too would
        # pull in every *other* region of the same island/country (confirmed
        # live: a "乌布" filter matched 佩尼达岛 chunks too, since both share
        # canonical_destination="巴厘岛"), which is precisely the kind of
        # unrelated-region noise a region-scoped query shouldn't return.
        values.add(canon["canonical_region"])
        fields = ("canonical_region", "destination_region")
    else:
        # Resolves to a whole destination (or isn't a known alias at all) --
        # match at the destination level, same as before this function
        # started canonicalizing its input.
        if canon.get("canonical_destination"):
            values.add(canon["canonical_destination"])
        fields = ("canonical_destination", "destination_city", "canonical_region", "destination_region")

    clauses = [{field: value} for value in values for field in fields]
    return {"$or": clauses}


def topic_overlap(metadata: Dict[str, Any], topic_filters: List[str]) -> bool:
    if not topic_filters:
        return True
    tagged = set((metadata.get("activity_topics") or "").split("|")) | set(
        (metadata.get("travel_styles") or "").split("|")
    )
    return bool(tagged & set(topic_filters))
