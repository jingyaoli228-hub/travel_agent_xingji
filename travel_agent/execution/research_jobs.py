"""Durable research jobs using RQ, Redis, and a PostgreSQL task ledger."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

from travel_agent.config.settings import get_settings
from travel_agent.persistence import database
from travel_agent.utils.logging import get_logger

_logger = get_logger("travel_agent.execution.research_jobs")
RESEARCH_PAUSE_NODE = "research_orchestrator"
_lock = threading.Lock()
_local_jobs: Dict[str, Dict[str, Any]] = {}
_worker_callbacks: Dict[str, Callable[[str, str], None]] = {}


def _durable() -> bool:
    settings = get_settings()
    return bool(settings.redis_url and settings.database_url)


def _checkpoint_id(snapshot: Any) -> str:
    try:
        return str(snapshot.config["configurable"]["checkpoint_id"])
    except (KeyError, TypeError):
        return "current"


def _redis_connection():
    from redis import Redis

    url = get_settings().redis_url
    if not url:
        raise RuntimeError("REDIS_URL is required for the research queue")
    client = Redis.from_url(url)
    client.ping()
    return client


def _make_progress_cb(session_id: str, key: Optional[str] = None) -> Callable[[str, str], None]:
    progress: dict[str, str] = {}

    def callback(worker: str, status: str) -> None:
        progress[worker] = status
        if key and database.enabled():
            database.update_task(key, "running", progress=dict(progress))
        else:
            with _lock:
                job = _local_jobs.get(session_id)
                if job:
                    job["progress"] = dict(progress)
                    job["updated_at"] = time.time()
    return callback


def get_progress_callback(session_id: str) -> Optional[Callable[[str, str], None]]:
    with _lock:
        callback = _worker_callbacks.get(session_id)
        if callback:
            return callback
        job = _local_jobs.get(session_id)
        return job.get("progress_cb") if job else None


def get_status(session_id: str) -> Dict[str, Any]:
    if _durable():
        task = database.latest_task(session_id)
        if not task:
            return {"status": "idle", "progress": {}}
        if task["status"] in ("queued", "running") and task.get("updated_at"):
            age = (datetime.now(timezone.utc) - task["updated_at"]).total_seconds()
            if age > get_settings().research_stale_after_seconds:
                database.mark_stale_tasks(get_settings().research_stale_after_seconds)
                task = database.latest_task(session_id) or task
        return {"status": task["status"], "progress": task.get("progress") or {},
                "error": task.get("error"), "attempts": task.get("attempts", 0)}
    with _lock:
        job = _local_jobs.get(session_id)
        if not job:
            return {"status": "idle", "progress": {}}
        return {"status": job["status"], "progress": dict(job["progress"]), "error": job.get("error")}


def is_running(session_id: str) -> bool:
    return get_status(session_id).get("status") in ("queued", "running")


def wait_until_done(session_id: str, timeout: Optional[float] = None, poll_interval: float = 0.2) -> bool:
    timeout = timeout or float(get_settings().research_job_timeout_seconds + 30)
    deadline = time.time() + timeout
    while is_running(session_id):
        if time.time() >= deadline:
            return False
        time.sleep(poll_interval)
    return True


def dispatch_if_needed(session_id: str, graph: Any, config: Dict[str, Any]) -> bool:
    snapshot = graph.get_state(config)
    if not snapshot or tuple(snapshot.next) != (RESEARCH_PAUSE_NODE,):
        return False
    if _durable():
        return _enqueue(session_id, snapshot)
    if get_settings().require_persistent_services:
        raise RuntimeError("Redis and PostgreSQL are required for durable background jobs")
    return _dispatch_thread(session_id, graph, config)


def retry_failed_if_paused(session_id: str, graph: Any, config: Dict[str, Any]) -> bool:
    """Treat a new user turn after terminal failure as an explicit retry."""
    if not _durable():
        return False
    task = database.latest_task(session_id)
    if not task or task["status"] != "error":
        return False
    snapshot = graph.get_state(config)
    if not snapshot or tuple(snapshot.next) != (RESEARCH_PAUSE_NODE,):
        return False
    database.allow_manual_retry(task["task_key"])
    return _enqueue(session_id, snapshot)


def _enqueue(session_id: str, snapshot: Any) -> bool:
    from rq import Queue, Retry

    settings = get_settings()
    key = database.task_key(session_id, _checkpoint_id(snapshot))
    rq_job_id = f"research-{key}-{uuid4().hex[:8]}"
    if not database.prepare_task(
        key, session_id, rq_job_id, settings.research_job_max_retries + 1
    ):
        task = database.latest_task(session_id)
        return bool(task and task["status"] in ("queued", "running"))
    queue = Queue(settings.research_queue_name, connection=_redis_connection())
    try:
        queue.enqueue(
            run_research_job, session_id, key, job_id=rq_job_id,
            job_timeout=settings.research_job_timeout_seconds,
            retry=Retry(max=settings.research_job_max_retries, interval=[15, 60]),
            result_ttl=86400, failure_ttl=7 * 86400,
        )
    except Exception as exc:
        database.update_task(
            key, "error", error=f"queue submission failed: {type(exc).__name__}",
            increment_attempt=True,
        )
        raise
    return True


def run_research_job(session_id: str, key: str) -> None:
    """RQ entry point; retries restart from the latest LangGraph checkpoint."""
    settings = get_settings()
    redis = _redis_connection()
    session_lock = redis.lock(
        f"travel-agent:research-lock:{session_id}",
        timeout=settings.research_job_timeout_seconds + 120,
        blocking_timeout=2,
    )
    if not session_lock.acquire(blocking=True):
        raise RuntimeError(f"research task already active for session {session_id}")
    callback = _make_progress_cb(session_id, key)
    with _lock:
        _worker_callbacks[session_id] = callback
    database.update_task(key, "running", progress={}, increment_attempt=True)
    try:
        from travel_agent.graph.workflow import get_compiled_graph

        graph = get_compiled_graph()
        config = {"configurable": {"thread_id": session_id}}
        while True:
            graph.invoke(None, config)
            snapshot = graph.get_state(config)
            if tuple(snapshot.next) == (RESEARCH_PAUSE_NODE,):
                continue
            break
        database.touch_session(session_id, stage=snapshot.values.get("stage"))
        database.update_task(key, "done")
    except Exception as exc:
        _logger.exception("research job failed for session %s", session_id)
        try:
            from rq import get_current_job
            current = get_current_job()
            will_retry = bool(current and (current.retries_left or 0) > 0)
        except Exception:
            will_retry = False
        database.update_task(
            key, "queued" if will_retry else "error",
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    finally:
        with _lock:
            _worker_callbacks.pop(session_id, None)
        try:
            session_lock.release()
        except Exception:
            pass


def _dispatch_thread(session_id: str, graph: Any, config: Dict[str, Any]) -> bool:
    with _lock:
        current = _local_jobs.get(session_id)
        if current and current["status"] == "running":
            return True
        callback = _make_progress_cb(session_id)
        _local_jobs[session_id] = {"status": "running", "progress": {}, "error": None,
                                   "updated_at": time.time(), "progress_cb": callback}
    threading.Thread(target=_run_local, args=(session_id, graph, config), daemon=True).start()
    return True


def _run_local(session_id: str, graph: Any, config: Dict[str, Any]) -> None:
    try:
        while True:
            graph.invoke(None, config)
            if tuple(graph.get_state(config).next) != (RESEARCH_PAUSE_NODE,):
                break
        with _lock:
            _local_jobs[session_id]["status"] = "done"
    except Exception as exc:
        with _lock:
            _local_jobs[session_id].update(status="error", error=str(exc))


def reconcile_stale_tasks() -> int:
    if not database.enabled():
        return 0
    return database.mark_stale_tasks(get_settings().research_stale_after_seconds)
