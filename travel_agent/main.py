"""FastAPI application entrypoint.

Run with:
    uvicorn travel_agent.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
import asyncio
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from travel_agent.api.chat import router as chat_router
from travel_agent.api.auth import router as auth_router, verify_token
from travel_agent.api.chat_stream import router as chat_stream_router
from travel_agent.api.workspace import router as workspace_router
from travel_agent.config.settings import get_settings

settings = get_settings()
request_identity: ContextVar[str | None] = ContextVar("request_identity", default=None)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from travel_agent.execution.research_jobs import reconcile_stale_tasks
    from travel_agent.graph.workflow import get_compiled_graph
    from travel_agent.persistence.database import init_schema

    if settings.require_persistent_services and not (settings.database_url and settings.redis_url and settings.chroma_host):
        raise RuntimeError("DATABASE_URL, REDIS_URL and CHROMA_HOST are mandatory in production")
    owner_auth_values = (settings.wechat_app_id, settings.wechat_app_secret, settings.owner_openid, settings.auth_token_secret)
    owner_auth_configured = all(owner_auth_values)
    if settings.environment.lower() == "production":
        if any(owner_auth_values) and not owner_auth_configured:
            raise RuntimeError("WeChat owner authentication is partially configured")
        if not owner_auth_configured and not (settings.legacy_trial_auth_enabled and settings.trial_access_key):
            raise RuntimeError("Configure owner WeChat authentication, or explicitly enable the legacy experience-preview credential")
        if not owner_auth_configured:
            logger.warning("legacy shared trial credential enabled; this is preview-only and does not enforce owner OpenID")
    init_schema()
    get_compiled_graph()  # creates/checks LangGraph checkpoint tables
    reconcile_stale_tasks()
    async def monitor_readiness() -> None:
        previous = None
        notified_state = None
        while True:
            await asyncio.sleep(30)
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
            state = "degraded" if any(value.startswith("error:") for value in services.values()) else "ready"
            if state != previous:
                logger.warning("readiness state changed: %s (%s)", state, services)
                if state == "degraded" and notified_state != state and settings.health_alert_webhook_url:
                    try:
                        import httpx
                        async with httpx.AsyncClient(timeout=5) as client:
                            await client.post(settings.health_alert_webhook_url, json={"text": f"行迹服务 {state}: {services}"})
                    except Exception:
                        logger.exception("health alert webhook delivery failed")
                notified_state = state
                previous = state

    monitor_task = asyncio.create_task(monitor_readiness())
    yield
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass

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


@app.middleware("http")
async def protect_trial_api(request: Request, call_next):
    """Require the configured owner's WeChat identity for every API call."""
    identity_token = None
    if request.url.path.startswith("/api/") and request.method != "OPTIONS" and request.url.path != "/api/auth/wechat":
        owner_auth_configured = all((settings.wechat_app_id, settings.wechat_app_secret, settings.owner_openid, settings.auth_token_secret))
        if owner_auth_configured:
            authorization = request.headers.get("Authorization", "")
            token = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
            claims = verify_token(token, settings.auth_token_secret or "") if token and settings.auth_token_secret else None
            if not claims:
                return JSONResponse(status_code=401, content={"detail": "微信登录已失效，请重新进入小程序"})
            if not settings.owner_openid or claims.get("sub") != settings.owner_openid:
                return JSONResponse(status_code=403, content={"detail": "此体验版仅允许所有者微信使用"})
            request.state.user_id = claims["sub"]
            identity_token = request_identity.set(claims["sub"])
        elif settings.trial_access_key and (
            settings.legacy_trial_auth_enabled or settings.environment.lower() != "production"
        ):
            # Explicitly opt-in for temporary experience previews; not an owner identity check.
            from secrets import compare_digest
            if not compare_digest(request.headers.get("X-Xingji-Trial-Key", ""), settings.trial_access_key):
                return JSONResponse(status_code=401, content={"detail": "体验版访问凭证无效"})
        elif settings.environment.lower() == "production":
            return JSONResponse(status_code=503, content={"detail": "服务端鉴权尚未配置"})
    try:
        return await call_next(request)
    finally:
        if identity_token is not None:
            request_identity.reset(identity_token)

app.include_router(chat_router, tags=["chat"])
app.include_router(auth_router)
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
    payload = {"status": "ready" if ready else "degraded", "services": services}
    if not ready:
        return JSONResponse(status_code=503, content=payload)
    return payload


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("travel_agent.main:app", host=settings.api_host, port=settings.api_port, reload=settings.debug)
