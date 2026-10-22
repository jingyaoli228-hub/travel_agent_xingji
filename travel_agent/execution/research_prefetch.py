"""Destination research prefetch used while the user confirms preferences.

The normal LangGraph research job remains authoritative.  This module only
starts the same broad research pass earlier and stores its structured result
in Redis (production) or process memory (local development).  The graph can
reuse that result after confirmation, then apply explicit must-go/exclusion
edits before ranking candidates.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, Optional
from uuid import uuid4

from travel_agent.config.settings import get_settings
from travel_agent.schemas.research_result import ResearchResult
from travel_agent.schemas.travel_requirement import TravelRequirement

_PREFIX = "travel-agent:research-prefetch:"
_TTL_SECONDS = 4 * 60 * 60
_lock = threading.Lock()
_local: Dict[str, Dict[str, Any]] = {}


def _redis():
    url = get_settings().redis_url
    if not url:
        return None
    from redis import Redis

    return Redis.from_url(url)


def _status_key(session_id: str) -> str:
    return f"{_PREFIX}{session_id}:status"


def _result_key(session_id: str) -> str:
    return f"{_PREFIX}{session_id}:result"


def dispatch(session_id: str, requirement: TravelRequirement) -> Dict[str, Any]:
    """Idempotently start a broad destination pass for this session."""
    if not requirement.destination:
        return {"status": "skipped", "reason": "destination_missing"}
    payload = requirement.model_dump(mode="json")
    redis = _redis()
    if redis is not None:
        if redis.exists(_result_key(session_id)):
            return {"status": "done"}
        created = redis.set(
            _status_key(session_id),
            json.dumps({"status": "queued", "progress": {}}, ensure_ascii=False),
            nx=True,
            ex=_TTL_SECONDS,
        )
        if not created:
            return get_status(session_id)
        from rq import Queue

        Queue(get_settings().research_queue_name, connection=redis).enqueue(
            run_prefetch_job,
            session_id,
            payload,
            job_id=f"research-prefetch-{session_id}-{uuid4().hex[:8]}",
            job_timeout=get_settings().research_job_timeout_seconds,
            result_ttl=_TTL_SECONDS,
            failure_ttl=_TTL_SECONDS,
        )
        return {"status": "queued", "progress": {}}

    with _lock:
        existing = _local.get(session_id)
        if existing and existing.get("status") in {"running", "done"}:
            return {"status": existing["status"], "progress": dict(existing.get("progress") or {})}
        _local[session_id] = {"status": "running", "progress": {}, "result": None, "updated_at": time.time()}
    threading.Thread(target=run_prefetch_job, args=(session_id, payload), daemon=True).start()
    return {"status": "running", "progress": {}}


def run_prefetch_job(session_id: str, requirement_data: Dict[str, Any]) -> None:
    """RQ/thread entry point.  Kept independent from the graph checkpoint."""
    redis = _redis()
    progress: Dict[str, str] = {}

    def report(worker: str, status: str) -> None:
        progress[worker] = status
        state = {"status": "running", "progress": progress}
        if redis is not None:
            redis.set(_status_key(session_id), json.dumps(state, ensure_ascii=False), ex=_TTL_SECONDS)
        else:
            with _lock:
                if session_id in _local:
                    _local[session_id].update(state, updated_at=time.time())

    try:
        if redis is not None:
            redis.set(
                _status_key(session_id),
                json.dumps({"status": "running", "progress": {}}, ensure_ascii=False),
                ex=_TTL_SECONDS,
            )
        from travel_agent.agents.research_agent import ResearchOrchestratorAgent

        result = ResearchOrchestratorAgent().run_full(TravelRequirement(**requirement_data), progress_cb=report)
        serialized = result.model_dump_json()
        if redis is not None:
            redis.set(_result_key(session_id), serialized, ex=_TTL_SECONDS)
            redis.set(
                _status_key(session_id),
                json.dumps({"status": "done", "progress": progress}, ensure_ascii=False),
                ex=_TTL_SECONDS,
            )
        else:
            with _lock:
                _local[session_id].update(status="done", progress=dict(progress), result=serialized, updated_at=time.time())
    except Exception as exc:  # noqa: BLE001 - surfaced through status; normal research remains fallback
        state = {"status": "error", "progress": progress, "error": f"{type(exc).__name__}: {exc}"}
        if redis is not None:
            redis.set(_status_key(session_id), json.dumps(state, ensure_ascii=False), ex=_TTL_SECONDS)
        else:
            with _lock:
                _local.setdefault(session_id, {}).update(state, updated_at=time.time())


def get_status(session_id: str) -> Dict[str, Any]:
    redis = _redis()
    if redis is not None:
        raw = redis.get(_status_key(session_id))
        return json.loads(raw) if raw else {"status": "idle", "progress": {}}
    with _lock:
        state = _local.get(session_id)
        if not state:
            return {"status": "idle", "progress": {}}
        return {
            "status": state.get("status", "idle"),
            "progress": dict(state.get("progress") or {}),
            "error": state.get("error"),
        }


def get_result(session_id: str) -> Optional[ResearchResult]:
    redis = _redis()
    if redis is not None:
        raw = redis.get(_result_key(session_id))
    else:
        with _lock:
            raw = (_local.get(session_id) or {}).get("result")
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return ResearchResult.model_validate_json(raw)
