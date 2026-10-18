"""FastAPI application entrypoint.

Run with:
    uvicorn travel_agent.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from travel_agent.api.chat import router as chat_router
from travel_agent.api.chat_stream import router as chat_stream_router
from travel_agent.api.workspace import router as workspace_router
from travel_agent.config.settings import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from travel_agent.execution.research_jobs import reconcile_stale_tasks
    from travel_agent.graph.workflow import get_compiled_graph
    from travel_agent.persistence.database import init_schema

    if settings.require_persistent_services and not (settings.database_url and settings.redis_url and settings.chroma_host):
        raise RuntimeError("DATABASE_URL, REDIS_URL and CHROMA_HOST are mandatory in production")
    init_schema()
    get_compiled_graph()  # creates/checks LangGraph checkpoint tables
    reconcile_stale_tasks()
    yield

app = FastAPI(
    title="Travel Planning Agent",
    description="LangGraph 驱动的企业级旅行规划 Agent (MVP)",
    version="0.1.0",
    lifespan=lifespan,
)

# Dev-time convenience for the Vite frontend (frontend/) when it isn't proxied
# through Vite's dev-server `server.proxy` -- harmless in this single-user
# demo-scale deployment, tighten `allow_origins` before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, tags=["chat"])
app.include_router(chat_stream_router, tags=["chat"])
app.include_router(workspace_router, tags=["workspace"])


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name}


@app.get("/health/ready")
def readiness() -> dict:
    from travel_agent.persistence.database import service_health

    services = service_health() if settings.database_url else {"postgres": "disabled"}
    try:
        import redis
        client = redis.Redis.from_url(settings.redis_url) if settings.redis_url else None
        if client:
            try:
                client.ping()
            finally:
                client.close()
        services["redis"] = "ok" if settings.redis_url else "disabled"
    except Exception as exc:
        services["redis"] = f"error:{type(exc).__name__}"
    try:
        if settings.chroma_host:
            from travel_agent.rag.chroma_client import heartbeat

            heartbeat()
            services["chroma"] = "ok"
        else:
            services["chroma"] = "embedded"
    except Exception as exc:
        services["chroma"] = f"error:{type(exc).__name__}"
    ready = all(value in ("ok", "embedded", "disabled") for value in services.values())
    return {"status": "ready" if ready else "degraded", "services": services}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("travel_agent.main:app", host=settings.api_host, port=settings.api_port, reload=settings.debug)
