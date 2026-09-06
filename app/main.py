"""FastAPI application entry point.

Wires together all routers, middleware, and lifecycle hooks.
"""

from __future__ import annotations

import structlog
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import get_settings
from app.db.session import engine
from app.middleware.audit import AuditMiddleware
from app.middleware.security import SecurityHeadersMiddleware
from app.api.limiter import limiter

logger = structlog.get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown lifecycle hooks."""
    logger.info("Starting up VASP Attribution Engine", env=settings.app_env)
    yield
    logger.info("Shutting down VASP Attribution Engine")
    await engine.dispose()


def create_app() -> FastAPI:
    """Application factory — returns a configured FastAPI instance."""
    app = FastAPI(
        title="Blockchain VASP Attribution Engine",
        description=(
            "LEA investigation platform for blockchain tracing, "
            "VASP attribution, risk scoring, and SAHYOG Portal integration."
        ),
        version="0.1.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
        default_response_class=JSONResponse,
        lifespan=lifespan,
    )

    # ── CORS — Fixed to explicitly allow port 3000
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Rate limiter (slowapi) ────────────────────────────────
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(SlowAPIMiddleware)

    # ── Temporarily disabled for Hackathon to fix CORS/Connectivity ──
    # app.add_middleware(AuditMiddleware)
    # app.add_middleware(SecurityHeadersMiddleware)

    # ── Routers ───────────────────────────────────────────────
    from app.api.v1 import router as api_v1_router  # noqa: PLC0415

    app.include_router(api_v1_router)

    # ── Health endpoint ───────────────────────────────────────
    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
