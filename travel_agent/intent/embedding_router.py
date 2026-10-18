"""Local embedding-free intent retriever.

No vector DB / embedding API is configured for this project. This mirrors
the situation `travel_agent/memory/episodic_memory.py` is already in -- it
falls back to tag-overlap similarity when chromadb isn't installed. This
module applies the same "graceful degradation" philosophy: a dependency-free
character n-gram + cosine-similarity engine stands in for an
`EmbeddingIntentRetriever` today, reading `intent_data/*.jsonl` as its
example bank. Swap `_vectorize`/`_cosine` for a real embedding-API call
later without touching any caller -- `EmbeddingIntentRetriever.retrieve()`'s
signature and `EmbeddingIntentResult` output shape are embedding-model-agnostic.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from travel_agent.intent.config import load_fusion_config
from travel_agent.intent.data_store import (
    load_feedback_examples,
    load_intent_examples,
    load_negative_examples,
)
from travel_agent.intent.schemas import (
    EmbeddingIntentResult,
    FeedbackCandidate,
    IntentCandidate,
    IntentContext,
    MatchedExample,
)

_TOKEN_RE = re.compile(r"[a-zA-Z]+|[一-鿿]")


def _char_ngrams(text: str, n: int) -> List[str]:
    """Character n-grams over normalized text -- robust, dependency-free
    tokenization for short, unsegmented Chinese phrases (no jieba needed)."""
    tokens = _TOKEN_RE.findall(text.lower())
    chars = list("".join(tokens)) if tokens else list(text.lower())
    if len(chars) < n:
        return ["".join(chars)] if chars else []
    return ["".join(chars[i : i + n]) for i in range(len(chars) - n + 1)]


def _vectorize(text: str) -> Counter:
    return Counter(_char_ngrams(text, 2) + _char_ngrams(text, 1))


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    dot = sum(a[k] * b[k] for k in common)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class _Entry:
    __slots__ = ("text", "label", "kind", "vector")

    def __init__(self, text: str, label: str, kind: str):
        self.text = text
        self.label = label
        self.kind = kind  # "intent" | "feedback" | "negative"
        self.vector = _vectorize(text)


@lru_cache(maxsize=1)
def _build_index() -> Tuple[_Entry, ...]:
    entries: List[_Entry] = []
    for ex in load_intent_examples():
        entries.append(_Entry(ex.text, ex.intent, "intent"))
    for ex in load_feedback_examples():
        entries.append(_Entry(ex.text, ex.feedback_type, "feedback"))
    for ex in load_negative_examples():
        entries.append(_Entry(ex.text, ex.intent, "negative"))
    return tuple(entries)


def clear_index_cache() -> None:
    """Call after `data_store.append_correction()` (or any edit to
    `intent_data/*.jsonl`) so the retriever picks up new/approved examples
    without a process restart."""
    _build_index.cache_clear()


class EmbeddingIntentRetriever:
    """Top-K retrieval + per-label voting over the local example bank."""

    def retrieve(self, message: str, context: Optional[IntentContext] = None) -> EmbeddingIntentResult:
        cfg = load_fusion_config().embedding
        query_vec = _vectorize(message or "")
        entries = _build_index()
        if not query_vec or not entries:
            return EmbeddingIntentResult()

        scored: List[Tuple[float, _Entry]] = []
        for entry in entries:
            score = _cosine(query_vec, entry.vector)
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[: cfg.top_k]

        intent_scores: Dict[str, float] = {}
        feedback_scores: Dict[str, float] = {}
        nearest: List[MatchedExample] = []
        negative_hit_score = 0.0

        for score, entry in top:
            nearest.append(MatchedExample(text=entry.text, intent=entry.label, score=round(score, 4)))
            if entry.kind == "intent":
                intent_scores[entry.label] = max(intent_scores.get(entry.label, 0.0), score)
            elif entry.kind == "feedback":
                feedback_scores[entry.label] = max(feedback_scores.get(entry.label, 0.0), score)
            elif entry.kind == "negative":
                negative_hit_score = max(negative_hit_score, score)

        # Negative-example penalty: an OOD match pulls every positive
        # candidate's score down, rather than only affecting the final tier.
        if negative_hit_score > 0:
            penalty = negative_hit_score * cfg.negative_penalty
            intent_scores = {k: max(0.0, v - penalty) for k, v in intent_scores.items()}

        intent_candidates = [
            IntentCandidate(intent=k, score=round(v, 4))
            for k, v in sorted(intent_scores.items(), key=lambda kv: kv[1], reverse=True)
        ]
        feedback_candidates = [
            FeedbackCandidate(feedback_type=k, score=round(v, 4))
            for k, v in sorted(feedback_scores.items(), key=lambda kv: kv[1], reverse=True)
        ]

        overall_confidence = intent_candidates[0].score if intent_candidates else 0.0
        if not intent_candidates and negative_hit_score > 0:
            overall_confidence = negative_hit_score  # confidently out-of-scope

        return EmbeddingIntentResult(
            intent_candidates=intent_candidates,
            feedback_candidates=feedback_candidates,
            nearest_examples=nearest,
            confidence=round(overall_confidence, 4),
        )
