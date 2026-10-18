"""Small psycopg persistence layer.

LangGraph owns its checkpoint tables.  This module owns application records
that do not belong in a checkpoint: workspace snapshots, durable task status,
profiles, and the append-only trip episode ledger.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from travel_agent.config.settings import get_settings


def enabled() -> bool:
    return bool(get_settings().database_url)


@contextmanager
def connection() -> Iterator[Any]:
    url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is required for durable state")
    import psycopg

    with psycopg.connect(url) as conn:
        yield conn


def init_schema() -> None:
    if not enabled():
        return
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS workspace_states (
                trip_id TEXT PRIMARY KEY,
                plan_version INTEGER NOT NULL,
                state JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT REFERENCES users(user_id),
                stage TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS task_runs (
                task_key TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                rq_job_id TEXT,
                status TEXT NOT NULL CHECK (status IN ('queued','running','done','error')),
                progress JSONB NOT NULL DEFAULT '{}'::jsonb,
                attempts INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                finished_at TIMESTAMPTZ
            );
            CREATE INDEX IF NOT EXISTS ix_task_runs_session_updated
                ON task_runs(session_id, updated_at DESC);
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT PRIMARY KEY,
                profile JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS trip_episodes (
                episode_key TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                episode JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS ix_trip_episodes_user_created
                ON trip_episodes(user_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS xhs_imports (
                import_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                source_text TEXT NOT NULL,
                parsed JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS ix_xhs_imports_user_created
                ON xhs_imports(user_id, created_at DESC);
            """
        )


def load_workspace(trip_id: str) -> Optional[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT state FROM workspace_states WHERE trip_id=%s", (trip_id,))
        row = cur.fetchone()
        return row[0] if row else None


def touch_session(session_id: str, user_id: Optional[str] = None, stage: Optional[str] = None) -> None:
    effective_user = user_id or session_id
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO users(user_id) VALUES (%s)
               ON CONFLICT(user_id) DO UPDATE SET last_seen_at=now()""",
            (effective_user,),
        )
        cur.execute(
            """INSERT INTO sessions(session_id,user_id,stage) VALUES (%s,%s,%s)
               ON CONFLICT(session_id) DO UPDATE SET
                 user_id=COALESCE(EXCLUDED.user_id,sessions.user_id),
                 stage=COALESCE(EXCLUDED.stage,sessions.stage), updated_at=now()""",
            (session_id, effective_user, stage),
        )


def list_sessions(user_id: str) -> list[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT session_id,stage,created_at,updated_at FROM sessions
               WHERE user_id=%s ORDER BY updated_at DESC""",
            (user_id,),
        )
        return [dict(zip(("session_id", "stage", "created_at", "updated_at"), row)) for row in cur.fetchall()]


def delete_trip_records(session_id: str) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM task_runs WHERE session_id=%s", (session_id,))
        cur.execute("DELETE FROM workspace_states WHERE trip_id=%s", (session_id,))
        cur.execute("DELETE FROM sessions WHERE session_id=%s", (session_id,))


def create_workspace(trip_id: str, version: int, state: dict[str, Any]) -> dict[str, Any]:
    from psycopg.types.json import Jsonb

    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO workspace_states(trip_id, plan_version, state)
               VALUES (%s,%s,%s) ON CONFLICT (trip_id) DO NOTHING""",
            (trip_id, version, Jsonb(state)),
        )
        cur.execute("SELECT state FROM workspace_states WHERE trip_id=%s", (trip_id,))
        return cur.fetchone()[0]


def save_workspace(trip_id: str, expected_version: int, state: dict[str, Any]) -> bool:
    """Compare-and-swap using the previous plan version.

    This turns plan_version into a real database optimistic lock.  Updates
    that intentionally keep the same version (preview/cache population) are
    serialized by the single API process and still guarded against a stale
    plan version.
    """
    from psycopg.types.json import Jsonb

    new_version = int(state["plan_version"])
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE workspace_states
               SET plan_version=%s, state=%s, updated_at=now()
               WHERE trip_id=%s AND plan_version=%s""",
            (new_version, Jsonb(state), trip_id, expected_version),
        )
        return cur.rowcount == 1


def task_key(session_id: str, checkpoint_id: str) -> str:
    return hashlib.sha256(f"{session_id}:{checkpoint_id}".encode()).hexdigest()[:40]


def prepare_task(key: str, session_id: str, rq_job_id: str, max_attempts: int) -> bool:
    """Create a task, or re-queue a previously failed task, atomically."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT status,attempts FROM task_runs WHERE task_key=%s FOR UPDATE", (key,))
        row = cur.fetchone()
        if row and row[0] in ("queued", "running", "done"):
            return False
        if row and row[0] == "error" and row[1] >= max_attempts:
            return False
        if row:
            cur.execute(
                """UPDATE task_runs SET status='queued', rq_job_id=%s, error=NULL,
                   progress='{}'::jsonb, updated_at=now(), finished_at=NULL WHERE task_key=%s""",
                (rq_job_id, key),
            )
        else:
            cur.execute(
                """INSERT INTO task_runs(task_key,session_id,rq_job_id,status)
                   VALUES (%s,%s,%s,'queued')""",
                (key, session_id, rq_job_id),
            )
        return True


def update_task(
    key: str,
    status: str,
    *,
    progress: Optional[dict[str, Any]] = None,
    error: Optional[str] = None,
    increment_attempt: bool = False,
) -> None:
    from psycopg.types.json import Jsonb

    finished = status in ("done", "error")
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE task_runs SET status=%s,
               progress=COALESCE(%s, progress), error=%s,
               attempts=attempts + %s, updated_at=now(),
               finished_at=CASE WHEN %s THEN now() ELSE NULL END
               WHERE task_key=%s""",
            (status, Jsonb(progress) if progress is not None else None, error,
             1 if increment_attempt else 0, finished, key),
        )


def latest_task(session_id: str) -> Optional[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT task_key,rq_job_id,status,progress,attempts,error,updated_at
               FROM task_runs WHERE session_id=%s ORDER BY updated_at DESC LIMIT 1""",
            (session_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return dict(zip(("task_key", "rq_job_id", "status", "progress", "attempts", "error", "updated_at"), row))


def allow_manual_retry(key: str) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE task_runs SET attempts=0, updated_at=now()
               WHERE task_key=%s AND status='error'""",
            (key,),
        )


def mark_stale_tasks(max_age_seconds: int) -> int:
    """Make orphaned API status truthful after a full worker/container loss."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """UPDATE task_runs SET status='error',
               error='worker interrupted or timed out; task may be submitted again',
               updated_at=now(), finished_at=now()
               WHERE status IN ('running','queued')
                 AND updated_at < now() - (%s * interval '1 second')""",
            (max_age_seconds,),
        )
        return cur.rowcount


def get_profile(user_id: str) -> Optional[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT profile FROM user_profiles WHERE user_id=%s", (user_id,))
        row = cur.fetchone()
        return row[0] if row else None


def save_profile(user_id: str, profile: dict[str, Any]) -> None:
    from psycopg.types.json import Jsonb

    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO users(user_id) VALUES (%s)
               ON CONFLICT(user_id) DO UPDATE SET last_seen_at=now()""",
            (user_id,),
        )
        cur.execute(
            """INSERT INTO user_profiles(user_id,profile) VALUES (%s,%s)
               ON CONFLICT(user_id) DO UPDATE SET profile=EXCLUDED.profile, updated_at=now()""",
            (user_id, Jsonb(profile)),
        )


def episode_key(episode: dict[str, Any]) -> str:
    # created_at is assigned immediately before persistence. Excluding it
    # makes a worker retry idempotent while still allowing materially changed
    # feedback/history from the same session to create another episode.
    payload = dict(episode)
    payload.pop("created_at", None)
    stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable.encode()).hexdigest()


def append_episode(episode: dict[str, Any]) -> None:
    from psycopg.types.json import Jsonb

    created = episode.get("created_at") or datetime.now(timezone.utc).isoformat()
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO trip_episodes(episode_key,user_id,session_id,episode,created_at)
               VALUES (%s,%s,%s,%s,%s) ON CONFLICT(episode_key) DO NOTHING""",
            (episode_key(episode), episode.get("user_id", ""), episode.get("session_id", ""), Jsonb(episode), created),
        )


def episodes_for_user(user_id: str) -> list[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT episode FROM trip_episodes WHERE user_id=%s ORDER BY created_at", (user_id,))
        return [row[0] for row in cur.fetchall()]


def save_xhs_import(import_id: str, user_id: str, source_text: str, parsed: dict[str, Any]) -> None:
    from psycopg.types.json import Jsonb

    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO xhs_imports(import_id,user_id,source_text,parsed)
               VALUES (%s,%s,%s,%s) ON CONFLICT(import_id) DO NOTHING""",
            (import_id, user_id, source_text, Jsonb(parsed)),
        )


def service_health() -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        with connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        result["postgres"] = "ok"
    except Exception as exc:  # health must report, not hide, dependency failure
        result["postgres"] = f"error:{type(exc).__name__}"
    return result
