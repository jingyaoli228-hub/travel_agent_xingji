"""L2 Trip Episodic Memory.

Lifecycle: cross-trip (keyed by `user_id`, spans many sessions). JSONL is
always written (unchanged, ground-truth ledger + the `RAG_DEGRADED`
fallback source) -- Round-6 Phase 4 additionally dual-writes each episode
into the `episodic_memory` ChromaDB collection (via the *shared* `rag/
chroma_client.py`, the same Chroma instance `travel_guides` lives in) as an
`EpisodicMemoryRecord` (requirement doc section 17), gated by a heuristic
`importance_score` so trivial episodes don't bloat the collection.

`retrieve_similar_trips()`'s signature/behavior is unchanged for existing
callers (`tags`-only Jaccard over JSONL, see `test_memory.py`) -- the new
`query_text` parameter is additive: when given and Chroma is available, it
tries real semantic search first, falling back to the original Jaccard path
on any failure (including Chroma being unavailable). This is the "vector
retrieval replaces Jaccard, Jaccard is the RAG_DEGRADED fallback" split from
docs/round6_rag_memory_eval_design.md section 6.
"""

from __future__ import annotations

import json
import hashlib
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from travel_agent.config.settings import get_settings
from travel_agent.memory.config import load_memory_config
from travel_agent.memory.schemas import EpisodicMemoryRecord
from travel_agent.persistence import database
from travel_agent.schemas.memory import TripEpisode
from travel_agent.utils.logging import get_logger

_logger = get_logger("travel_agent.memory.episodic")
_lock = threading.Lock()


def _jaccard(a: List[str], b: List[str]) -> float:
    set_a, set_b = set(a), set(b)
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


class _JsonlEpisodicStore:
    """Local JSON-lines store: one line per `TripEpisode`. Always written to,
    regardless of whether the Chroma dual-write succeeds."""

    def __init__(self, path: str) -> None:
        self._path = path
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    def append(self, episode: TripEpisode) -> None:
        if database.enabled():
            database.append_episode(episode.model_dump(mode="json"))
            return
        with _lock:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(episode.model_dump(), ensure_ascii=False) + "\n")

    def all_for_user(self, user_id: str) -> List[TripEpisode]:
        if database.enabled():
            return [TripEpisode(**row) for row in database.episodes_for_user(user_id)]
        if not os.path.exists(self._path):
            return []
        episodes: List[TripEpisode] = []
        with _lock:
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except ValueError:
                        continue
                    if data.get("user_id") == user_id:
                        episodes.append(TripEpisode(**data))
        return episodes


def _episode_to_record(episode: TripEpisode) -> EpisodicMemoryRecord:
    summary_parts = []
    if episode.destination:
        summary_parts.append(f"目的地：{episode.destination}")
    if episode.selected_experiences:
        names = [e.get("name", str(e)) for e in episode.selected_experiences]
        summary_parts.append(f"选择了：{'、'.join(names)}")
    if episode.rejected_experiences:
        summary_parts.append(f"拒绝了：{'、'.join(episode.rejected_experiences)}")
    if episode.feedback:
        summary_parts.append(f"反馈：{'；'.join(episode.feedback)}")
    event_summary = "；".join(summary_parts) or f"{episode.destination or '一次'}旅行记录"

    if episode.feedback and episode.rejected_experiences:
        event_type = "feedback_and_rejection"
    elif episode.feedback:
        event_type = "user_feedback"
    elif episode.rejected_experiences:
        event_type = "rejected_option"
    else:
        event_type = "trip_completed"

    # Baseline 0.3: a completed trip is, on its own, a valid write trigger
    # per requirement doc section 21 -- richer content (feedback, rejected
    # options, tags) pushes it further above the config threshold.
    importance = 0.3
    if episode.feedback:
        importance += 0.25
    if episode.rejected_experiences:
        importance += 0.2
    if episode.tags:
        importance += 0.15
    if episode.budget_difference:
        importance += 0.1
    importance = round(min(importance, 1.0), 2)

    identity = episode.model_dump(mode="json")
    identity.pop("created_at", None)
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
    return EpisodicMemoryRecord(
        memory_id=f"{episode.user_id}:{episode.session_id}:{digest}",
        user_id=episode.user_id,
        session_id=episode.session_id,
        event_type=event_type,
        event_summary=event_summary,
        destinations=[episode.destination] if episode.destination else [],
        entities=list(episode.tags),
        user_feedback=list(episode.feedback),
        decisions=[e.get("name", str(e)) for e in episode.selected_experiences],
        rejected_options=list(episode.rejected_experiences),
        importance_score=importance,
        created_at=episode.created_at or datetime.now(timezone.utc).isoformat(),
    )


def _record_to_episode(record: EpisodicMemoryRecord) -> TripEpisode:
    """Approximate reconstruction for semantic-search results -- not a
    perfect inverse of `_episode_to_record` (e.g. `final_plan_summary`/
    `budget_difference` aren't preserved in the Chroma record), but callers
    of `retrieve_similar_trips()` only read `destination`/tags/feedback/
    selected/rejected experiences today."""
    return TripEpisode(
        user_id=record.user_id,
        session_id=record.session_id,
        destination=record.destinations[0] if record.destinations else "",
        selected_experiences=[{"name": d} for d in record.decisions],
        rejected_experiences=list(record.rejected_options),
        feedback=list(record.user_feedback),
        tags=list(record.entities),
        created_at=record.created_at,
    )


class EpisodicMemory:
    """L2 accessor. JSONL is the always-on store; ChromaDB is an additive
    dual-write/semantic-read layer, degrading silently on any failure."""

    def __init__(self) -> None:
        settings = get_settings()
        self._store = _JsonlEpisodicStore(settings.episodic_memory_path)

    def add_episode(self, episode: TripEpisode) -> None:
        if not episode.created_at:
            episode.created_at = datetime.now(timezone.utc).isoformat()
        self._store.append(episode)
        self._write_to_chroma(episode)

    def _write_to_chroma(self, episode: TripEpisode) -> None:
        record = _episode_to_record(episode)
        if record.importance_score < load_memory_config().episodic_importance_threshold:
            return
        try:
            from travel_agent.rag.chroma_client import get_collection
            from travel_agent.rag.config import load_rag_config

            collection = get_collection(load_rag_config().collections.episodic_memory)
            collection.upsert(
                ids=[record.memory_id],
                documents=[record.event_summary],
                metadatas=[
                    {
                        "user_id": record.user_id,
                        "session_id": record.session_id,
                        "event_type": record.event_type,
                        "destinations": "|".join(record.destinations),
                        "importance_score": record.importance_score,
                        "created_at": record.created_at,
                        "_record_json": record.model_dump_json(),
                    }
                ],
            )
        except Exception as exc:  # noqa: BLE001 -- JSONL write above already succeeded; degrade quietly
            _logger.warning("episodic memory: chroma dual-write failed, JSONL-only for this episode: %s", exc)

    def retrieve_similar_trips(
        self, user_id: str, tags: List[str], top_k: int = 3, query_text: str = ""
    ) -> List[TripEpisode]:
        if query_text:
            semantic = self._retrieve_semantic(user_id, query_text, top_k)
            if semantic:
                return semantic

        episodes = self._store.all_for_user(user_id)
        if not episodes:
            return []
        scored = [(_jaccard(tags, e.tags), e) for e in episodes]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [e for score, e in scored[:top_k] if score > 0] or episodes[-top_k:]

    def _retrieve_semantic(self, user_id: str, query_text: str, top_k: int) -> List[TripEpisode]:
        try:
            from travel_agent.rag.chroma_client import get_collection
            from travel_agent.rag.config import load_rag_config

            collection = get_collection(load_rag_config().collections.episodic_memory)
            result = collection.query(query_texts=[query_text], n_results=top_k, where={"user_id": user_id})
            episodes: List[TripEpisode] = []
            for metadata in (result.get("metadatas") or [[]])[0]:
                raw = metadata.get("_record_json")
                if not raw:
                    continue
                episodes.append(_record_to_episode(EpisodicMemoryRecord(**json.loads(raw))))
            return episodes
        except Exception as exc:  # noqa: BLE001 -- RAG_DEGRADED: fall back to Jaccard/JSONL
            _logger.warning("episodic memory: chroma semantic search failed, falling back to Jaccard: %s", exc)
            return []

    def all_for_user(self, user_id: str) -> List[TripEpisode]:
        return self._store.all_for_user(user_id)
