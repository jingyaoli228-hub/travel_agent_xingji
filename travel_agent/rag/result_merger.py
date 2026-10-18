"""Merge/Dedup/Fusion (requirement doc section 13): Normalize -> Deduplicate
-> Score Fusion -> Diversity Control, run on the combined chunk list out of
`parallel_retriever.py` before it reaches `reranker.py`.

Fusion-weight renormalization gotcha (same issue Stage-3's intent fusion
resolver hit, see docs/round6_rag_memory_eval_design.md's stage-3 memory
note): most chunks only have 1-2 of the 5 score components populated (an
episodic-memory chunk has no `dense_score`/`keyword_score` at all). Applying
the configured weights against a fixed denominator would systematically
punish single-source chunks for a coverage gap that isn't their fault --
weights are renormalized over whichever components are actually present.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Dict, List

from travel_agent.rag.config import FusionWeights, load_rag_config
from travel_agent.rag.schemas import RetrievedChunk

_NEAR_DUPLICATE_RATIO = 0.9


def _merge_duplicate_ids(chunks: List[RetrievedChunk]) -> List[RetrievedChunk]:
    """The same underlying chunk (by `chunk_id`) can come back from more than
    one retriever (dense AND keyword both matching it) -- combine their
    per-source scores into one record instead of keeping separate rows."""
    by_id: Dict[str, RetrievedChunk] = {}
    for chunk in chunks:
        existing = by_id.get(chunk.chunk_id)
        if existing is None:
            by_id[chunk.chunk_id] = chunk.model_copy()
            continue
        for field in ("dense_score", "keyword_score", "metadata_score", "source_quality_score", "freshness_score"):
            new_value = getattr(chunk, field)
            if new_value is not None and getattr(existing, field) is None:
                setattr(existing, field, new_value)
        existing.retriever = f"{existing.retriever}+{chunk.retriever}" if chunk.retriever not in existing.retriever else existing.retriever
    return list(by_id.values())


def _fuse_score(chunk: RetrievedChunk, weights: FusionWeights) -> float:
    components = [
        (weights.dense, chunk.dense_score),
        (weights.keyword, chunk.keyword_score),
        (weights.metadata, chunk.metadata_score),
        (weights.source_quality, chunk.source_quality_score),
        (weights.freshness, chunk.freshness_score),
    ]
    available = [(w, s) for w, s in components if s is not None]
    if not available:
        return 0.0
    total_weight = sum(w for w, _ in available)
    if total_weight <= 0:
        return 0.0
    return sum(w * s for w, s in available) / total_weight


def _drop_near_duplicate_content(chunks: List[RetrievedChunk]) -> List[RetrievedChunk]:
    """Requirement doc section 13: "同一笔记或同一地点的重复片段不能多次占用
    上下文". Different `chunk_id`s can still describe the same thing (e.g.
    two separate notes both covering 乌布瑜伽) -- drop the lower-scored one
    when their content is near-identical. O(n^2) but n is small post-merge
    (candidate lists here are a handful to a few dozen, not the full
    collection)."""
    ordered = sorted(chunks, key=lambda c: c.combined_score, reverse=True)
    kept: List[RetrievedChunk] = []
    for chunk in ordered:
        is_duplicate = any(
            other.source_type == chunk.source_type
            and SequenceMatcher(None, chunk.content[:300], other.content[:300]).ratio() >= _NEAR_DUPLICATE_RATIO
            for other in kept
        )
        if not is_duplicate:
            kept.append(chunk)
    return kept


def _apply_diversity_cap(chunks: List[RetrievedChunk], max_per_parent: int = 3) -> List[RetrievedChunk]:
    """Cap how many chunks from the same source note (`parent_document_id`)
    survive, so one long note can't monopolize the context window ahead of
    `reranker.py`. Order (already score-sorted) is otherwise preserved."""
    counts: Dict[str, int] = {}
    kept: List[RetrievedChunk] = []
    for chunk in chunks:
        parent = chunk.metadata.get("parent_document_id") or chunk.chunk_id
        counts[parent] = counts.get(parent, 0) + 1
        if counts[parent] <= max_per_parent:
            kept.append(chunk)
    return kept


def merge_and_score(chunks: List[RetrievedChunk], max_per_parent: int = 3) -> List[RetrievedChunk]:
    if not chunks:
        return []

    weights = load_rag_config().fusion_weights
    merged = _merge_duplicate_ids(chunks)
    for chunk in merged:
        chunk.combined_score = _fuse_score(chunk, weights)

    deduped = _drop_near_duplicate_content(merged)
    diverse = _apply_diversity_cap(deduped, max_per_parent=max_per_parent)
    return sorted(diverse, key=lambda c: c.combined_score, reverse=True)
