"""Loads `intent_data/*.{yaml,jsonl}` -- the taxonomy and the intent/feedback/
negative example banks used by `embedding_router.py` and `fusion_resolver.py`.
Centralized here so both share one cached view of the data instead of each
re-parsing the files independently, and so cache invalidation (on a
correction being filed) has one place to happen.

This is also where the lightweight, local version of the design doc's
section-18 "online correction" loop lives: `append_correction()` appends a
`review_status="pending"` row to `negative_examples.jsonl` instead of writing
straight into the production example bank. A human bumps `review_status` to
`"approved"` (and ideally promotes it into `intent_examples.jsonl`) before it
is picked up by `load_negative_examples()` / embedding retrieval -- no
example ever reaches the live matcher unreviewed.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import yaml
from pydantic import BaseModel

from travel_agent.config.settings import get_settings


class IntentExample(BaseModel):
    text: str
    intent: str
    task_type: str = ""
    operation: str = ""
    target: str = ""
    kind: str = "positive"
    review_status: str = "approved"


class FeedbackExample(BaseModel):
    text: str
    feedback_type: str


def _data_dir() -> Path:
    return Path(get_settings().intent_data_dir)


def _read_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    rows: List[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


@lru_cache(maxsize=1)
def load_taxonomy() -> Dict[str, Any]:
    path = _data_dir() / "intent_taxonomy.yaml"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def load_intent_examples() -> List[IntentExample]:
    rows = _read_jsonl(_data_dir() / "intent_examples.jsonl")
    return [IntentExample(**r) for r in rows]


@lru_cache(maxsize=1)
def load_feedback_examples() -> List[FeedbackExample]:
    rows = _read_jsonl(_data_dir() / "feedback_examples.jsonl")
    return [FeedbackExample(**r) for r in rows]


@lru_cache(maxsize=1)
def load_negative_examples() -> List[IntentExample]:
    rows = _read_jsonl(_data_dir() / "negative_examples.jsonl")
    approved = [r for r in rows if r.get("review_status", "approved") == "approved"]
    return [IntentExample(**r) for r in approved]


def append_correction(original_message: str, predicted_intent: str, corrected_intent: str, context_phase: str) -> None:
    """File a user correction as a pending, unreviewed sample."""
    path = _data_dir() / "negative_examples.jsonl"
    record = {
        "text": original_message,
        "intent": corrected_intent,
        "predicted_intent": predicted_intent,
        "context_phase": context_phase,
        "kind": "correction",
        "review_status": "pending",
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    load_negative_examples.cache_clear()


def clear_caches() -> None:
    load_taxonomy.cache_clear()
    load_intent_examples.cache_clear()
    load_feedback_examples.cache_clear()
    load_negative_examples.cache_clear()
