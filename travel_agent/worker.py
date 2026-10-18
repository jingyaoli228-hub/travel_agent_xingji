"""Single-concurrency RQ worker entrypoint for the Compose service."""

from __future__ import annotations

from redis import Redis
from rq import Queue, Worker

from travel_agent.config.settings import get_settings
from travel_agent.execution.research_jobs import reconcile_stale_tasks
from travel_agent.persistence.database import init_schema


def main() -> None:
    settings = get_settings()
    if not settings.redis_url or not settings.database_url:
        raise RuntimeError("Worker requires REDIS_URL and DATABASE_URL")
    init_schema()
    reconcile_stale_tasks()
    connection = Redis.from_url(settings.redis_url)
    queue = Queue(settings.research_queue_name, connection=connection)
    # One Worker consumes one job at a time. RQ's scheduler handles the two
    # bounded retry intervals configured at enqueue time.
    Worker([queue], connection=connection).work(with_scheduler=True)


if __name__ == "__main__":
    main()
