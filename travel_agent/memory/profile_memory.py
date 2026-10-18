"""L3 User Profile Memory.

Lifecycle: long-term (survives indefinitely, keyed by `user_id`). The flat
JSON "Profile Store" (`get()`/`upsert()`) is kept exactly as before for
backward compatibility -- `MemoryManager.retrieve_memory()` and every
existing caller keep working unmodified.

Round-6 Phase 4 additionally dual-writes each non-empty field `upsert()`
receives as its own `UserProfileStatement` (requirement doc section 18) into
the `user_profile` ChromaDB collection: one record *per preference
dimension*, not one big record per user, with a confidence/evidence-count/
status state machine (section 19). `get_statements()` is the new read side
of that -- it falls back to deriving statements from the flat JSON profile
when Chroma is unavailable, so it's still useful in `RAG_DEGRADED` mode.

Evidence-strength note: `upsert()` only receives already-extracted
structured fields, not the user's raw sentence, so this layer can't tell
"这次想" (session-only) from "我一直都" (stable) the way the requirement doc's
example does -- that classification needs the raw utterance and belongs
upstream (a future intent-layer concern). Here, every new dimension starts
as `TENTATIVE_PROFILE` and only becomes `STABLE_PROFILE` once reinforced
`profile_stable_evidence_count` times (config/memory.yaml), which is a
defensible proxy for "多次重复出现同一偏好" (section 19/21) without requiring
NLP language-strength detection this call site doesn't have the input for.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from travel_agent.config.settings import get_settings
from travel_agent.memory.config import load_memory_config
from travel_agent.memory.schemas import UserProfileStatement
from travel_agent.persistence import database
from travel_agent.schemas.memory import UserProfile
from travel_agent.utils.logging import get_logger

_lock = threading.Lock()
_logger = get_logger("travel_agent.memory.profile")

_DIMENSION_LABELS = {
    "travel_style": "旅行风格",
    "hotel_preference": "住宿偏好",
    "interest_preference": "兴趣偏好",
    "food_constraints": "饮食限制",
    "transport_preference": "交通偏好",
}
_KNOWN_DIMENSIONS = tuple(_DIMENSION_LABELS)


def _statement_text(dimension: str, value: Any) -> str:
    label = _DIMENSION_LABELS.get(dimension, dimension)
    value_str = "、".join(value) if isinstance(value, list) else str(value)
    return f"{label}：{value_str}"


class ProfileMemory:
    """L3 accessor: one `UserProfile` per user, persisted as a JSON file
    (unchanged), plus per-dimension `UserProfileStatement`s in ChromaDB
    (new, additive)."""

    def __init__(self) -> None:
        self._path = get_settings().user_profile_store_path
        import os

        directory = os.path.dirname(self._path)
        if directory:
            os.makedirs(directory, exist_ok=True)

    def _read_all(self) -> Dict[str, Any]:
        if database.enabled():
            # Callers only need point lookup in production; returning an
            # empty mapping here avoids pretending PostgreSQL is a flat file.
            return {}
        import os

        if not os.path.exists(self._path):
            return {}
        with _lock:
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (ValueError, OSError):
                return {}

    def _write_all(self, data: Dict[str, Any]) -> None:
        with _lock:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def get(self, user_id: str) -> Optional[UserProfile]:
        if database.enabled():
            data = database.get_profile(user_id)
            return UserProfile(**data) if data else None
        data = self._read_all().get(user_id)
        return UserProfile(**data) if data else None

    def upsert(self, user_id: str, session_id: str = "", **fields: Any) -> UserProfile:
        all_data = self._read_all()
        current = self.get(user_id) if database.enabled() else None
        existing = current.model_dump() if current else all_data.get(user_id, {"user_id": user_id})
        for key, value in fields.items():
            if value in (None, [], ""):
                continue
            if key in ("interest_preference", "food_constraints") and isinstance(value, list):
                merged = list(dict.fromkeys((existing.get(key) or []) + value))
                existing[key] = merged
            else:
                existing[key] = value
            self._reinforce_or_create_statement(user_id, session_id, key, existing[key])
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()
        if database.enabled():
            database.save_profile(user_id, existing)
        else:
            all_data[user_id] = existing
            self._write_all(all_data)
        return UserProfile(**existing)

    # -- Round-6: per-statement Chroma dual-write ---------------------------

    def _reinforce_or_create_statement(self, user_id: str, session_id: str, dimension: str, value: Any) -> None:
        try:
            from travel_agent.rag.chroma_client import get_collection
            from travel_agent.rag.config import load_rag_config

            collection = get_collection(load_rag_config().collections.user_profile)
        except Exception as exc:  # noqa: BLE001 -- JSON write already succeeded; degrade quietly
            _logger.warning("profile memory: chroma unavailable, skipping statement dual-write: %s", exc)
            return

        profile_id = f"{user_id}:{dimension}"
        now = datetime.now(timezone.utc).isoformat()
        threshold = load_memory_config().profile_stable_evidence_count

        existing = collection.get(ids=[profile_id])
        record: Optional[UserProfileStatement] = None
        if existing.get("ids"):
            raw = (existing.get("metadatas") or [{}])[0].get("_statement_json")
            if raw:
                try:
                    record = UserProfileStatement(**json.loads(raw))
                except (ValueError, TypeError):
                    record = None

        if record is not None:
            merged_value = value
            if isinstance(record.value, list) and isinstance(value, list):
                merged_value = list(dict.fromkeys(record.value + value))
            record.value = merged_value
            record.statement = _statement_text(dimension, merged_value)
            is_new_evidence = not session_id or session_id not in record.source_session_ids
            if is_new_evidence:
                record.evidence_count += 1
                record.confidence = round(min(1.0, record.confidence + 0.15), 2)
            if session_id and session_id not in record.source_session_ids:
                record.source_session_ids.append(session_id)
            record.last_updated_at = now
            if record.evidence_count >= threshold:
                record.status = "STABLE_PROFILE"
        else:
            record = UserProfileStatement(
                profile_id=profile_id,
                user_id=user_id,
                statement=_statement_text(dimension, value),
                preference_dimension=dimension,
                value=value,
                confidence=0.5,
                evidence_count=1,
                source_session_ids=[session_id] if session_id else [],
                first_observed_at=now,
                last_updated_at=now,
                status="TENTATIVE_PROFILE",
            )

        try:
            collection.upsert(
                ids=[profile_id],
                documents=[record.statement],
                metadatas=[
                    {
                        "user_id": user_id,
                        "preference_dimension": dimension,
                        "status": record.status,
                        "confidence": record.confidence,
                        "evidence_count": record.evidence_count,
                        "_statement_json": record.model_dump_json(),
                    }
                ],
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning("profile memory: chroma statement upsert failed: %s", exc)

    def get_statements(self, user_id: str) -> List[UserProfileStatement]:
        """Per-dimension statements, newest source of truth for Phase 5's
        Memory Context Builder. Falls back to deriving statements from the
        flat JSON profile when Chroma is unavailable."""
        try:
            from travel_agent.rag.chroma_client import get_collection
            from travel_agent.rag.config import load_rag_config

            collection = get_collection(load_rag_config().collections.user_profile)
            rows = collection.get(where={"user_id": user_id})
            statements = []
            for metadata in rows.get("metadatas", []):
                raw = metadata.get("_statement_json")
                if raw:
                    statements.append(UserProfileStatement(**json.loads(raw)))
            if statements:
                return statements
        except Exception as exc:  # noqa: BLE001 -- RAG_DEGRADED: fall back to JSON-derived statements
            _logger.warning("profile memory: chroma read failed, deriving statements from JSON: %s", exc)

        return self._statements_from_json_fallback(user_id)

    def _statements_from_json_fallback(self, user_id: str) -> List[UserProfileStatement]:
        profile = self.get(user_id)
        if profile is None:
            return []
        now = profile.updated_at or datetime.now(timezone.utc).isoformat()
        statements = []
        for dimension in _KNOWN_DIMENSIONS:
            value = getattr(profile, dimension, None)
            if not value:
                continue
            statements.append(
                UserProfileStatement(
                    profile_id=f"{user_id}:{dimension}",
                    user_id=user_id,
                    statement=_statement_text(dimension, value),
                    preference_dimension=dimension,
                    value=value,
                    confidence=0.5,
                    evidence_count=1,
                    first_observed_at=now,
                    last_updated_at=now,
                    status="TENTATIVE_PROFILE",
                )
            )
        return statements
