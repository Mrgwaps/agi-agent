from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle."""
    logger.info("Starting %s...", settings.app_name)

    # Import tools package so all tools self-register
    import app.tools  # noqa: F401

    # Optional: set up OpenTelemetry
    if settings.otel_enabled:
        _setup_telemetry()

    # Warm up memory connections (best-effort)
    from app.memory.session import session_memory
    from app.memory.longterm import longterm_memory
    from app.memory.vector_store import vector_store

    try:
        await session_memory._get_client()
        logger.info("Redis session memory: connected")
    except Exception as exc:
        logger.warning("Redis unavailable: %s", exc)

    try:
        await longterm_memory._get_pool()
    except Exception as exc:
        logger.warning("Postgres unavailable: %s", exc)

    try:
        await vector_store._get_collection()
    except Exception as exc:
        logger.warning("ChromaDB unavailable: %s", exc)

    # Start 30-minute heartbeat intelligence loop (uses background_openrouter_client)
    from app.api.heartbeat import heartbeat_loop
    _heartbeat_task = asyncio.create_task(heartbeat_loop())
    logger.info("Heartbeat intelligence loop started (30-min interval)")

    # Start perpetual skill researcher (2-hour cycles, uses background_openrouter_client)
    from app.services.skill_researcher import skill_researcher_loop
    _skill_task = asyncio.create_task(skill_researcher_loop())
    logger.info("Skill researcher started (2-hour cycles, deepseek-r1:free)")

    logger.info("%s ready.", settings.app_name)
    yield

    # Shutdown
    logger.info("Shutting down %s...", settings.app_name)
    from app.memory.session import session_memory
    from app.memory.longterm import longterm_memory

    await session_memory.close()
    await longterm_memory.close()
    logger.info("Shutdown complete.")


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="AGI Demo Agent — FastAPI backend with LangGraph orchestration",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # ── CORS ────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )

    # ── Request timing middleware ────────────────────────────────────────────
    @app.middleware("http")
    async def timing_middleware(request: Request, call_next: Any) -> Any:
        t0 = time.monotonic()
        response = await call_next(request)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        response.headers["X-Process-Time-Ms"] = str(elapsed_ms)
        return response

    # ── Global exception handler ─────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception(
            "Unhandled exception on %s %s: %s",
            request.method,
            request.url.path,
            exc,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "detail": str(exc),
                "path": request.url.path,
            },
        )

    # ── Routers ──────────────────────────────────────────────────────────────
    from app.api.tasks import router as tasks_router
    from app.api.tools import router as tools_router
    from app.api.memory import router as memory_router
    from app.api.eval import router as eval_router
    from app.api.voice import router as voice_router
    from app.api.heartbeat import router as heartbeat_router
    from app.api.email_api import router as email_router
    from app.api.payments import router as payments_router
    from app.api.webhooks import router as webhooks_router
    from app.api.skills import router as skills_router

    app.include_router(tasks_router)
    app.include_router(tools_router)
    app.include_router(memory_router)
    app.include_router(eval_router)
    app.include_router(voice_router)
    app.include_router(heartbeat_router)
    app.include_router(email_router)
    app.include_router(payments_router)
    app.include_router(webhooks_router)
    app.include_router(skills_router)

    # ── Health check ─────────────────────────────────────────────────────────
    @app.get("/health", tags=["system"])
    async def health_check() -> Dict[str, Any]:
        from app.memory.session import session_memory
        from app.services.ollama_service import ollama_service

        redis_ok = False
        try:
            client = await session_memory._get_client()
            await client.ping()
            redis_ok = True
        except Exception:
            pass

        ollama_ok = await ollama_service.is_available()

        return {
            "status": "ok",
            "service": settings.app_name,
            "version": "1.0.0",
            "dependencies": {
                "redis": "up" if redis_ok else "down",
                "ollama": "up" if ollama_ok else "down",
            },
        }

    @app.get("/", tags=["system"])
    async def root() -> Dict[str, str]:
        return {
            "service": settings.app_name,
            "docs": "/docs",
            "health": "/health",
        }

    return app


def _setup_telemetry() -> None:
    """Initialise OpenTelemetry SDK (best-effort)."""
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )

        provider = TracerProvider()
        trace.set_tracer_provider(provider)
        logger.info("OpenTelemetry initialised (in-memory exporter)")
    except Exception as exc:
        logger.warning("OpenTelemetry setup failed (non-fatal): %s", exc)


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
