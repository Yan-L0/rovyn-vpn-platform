from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy import text

from vpn_platform.api.routes import router
from vpn_platform.core.config import get_settings
from vpn_platform.db.session import create_engine, create_session_factory
from vpn_platform.providers.remnawave import RemnawaveProvider

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = create_engine(settings.DATABASE_URL)
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    provider = None
    if settings.REMNAWAVE_BASE_URL and settings.REMNAWAVE_API_TOKEN.get_secret_value():
        provider = RemnawaveProvider(
            settings.REMNAWAVE_BASE_URL,
            settings.REMNAWAVE_API_TOKEN.get_secret_value(),
            settings.HTTP_TIMEOUT_SECONDS,
        )

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.redis = redis
    app.state.vpn_provider = provider
    yield
    if provider is not None:
        await provider.close()
    await redis.aclose()
    await engine.dispose()


settings = get_settings()
app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production_like else None,
    redoc_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(settings.MINIAPP_PUBLIC_URL).rstrip("/")],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID", "Idempotency-Key"],
)
app.include_router(router)


@app.get("/health/live", include_in_schema=False)
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
async def ready(request: Request, response: Response) -> dict[str, object]:
    checks: dict[str, bool] = {"postgres": False, "redis": False, "vpn_provider": False}
    try:
        async with request.app.state.session_factory() as db:
            await db.execute(text("SELECT 1"))
        checks["postgres"] = True
    except Exception:
        logger.warning("PostgreSQL readiness check failed", exc_info=True)
    try:
        await request.app.state.redis.ping()
        checks["redis"] = True
    except Exception:
        logger.warning("Redis readiness check failed", exc_info=True)
    provider = request.app.state.vpn_provider
    if provider is not None:
        checks["vpn_provider"] = (await provider.health()).healthy

    required = checks["postgres"] and checks["redis"]
    if request.app.state.settings.is_production_like:
        required = required and checks["vpn_provider"]
    if not required:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if required else "not_ready", "checks": checks}
