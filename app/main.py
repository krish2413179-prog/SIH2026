"""FastAPI application entry point.

Wires together all routers, middleware, and lifecycle hooks.
"""

from __future__ import annotations

import re
import structlog
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
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

# Pre-compile CORS origin patterns once at module level.
_CORS_REGEX = re.compile(r"https://.*\.(vercel\.app|render\.com|railway\.app)$")

_FALLBACK_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
]


def _get_allowed_origins() -> list[str]:
    return list(dict.fromkeys(settings.cors_origins_list + _FALLBACK_ORIGINS))


def _is_allowed_origin(origin: str) -> bool:
    """Return True if *origin* is explicitly listed or matches the regex."""
    return origin in _get_allowed_origins() or bool(_CORS_REGEX.match(origin))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown lifecycle hooks."""
    logger.info("Starting up VASP Attribution Engine", env=settings.app_env)
    try:
        async with engine.begin() as conn:
            from sqlalchemy import text
            await conn.execute(text("UPDATE trace_jobs SET status = 'cancelled' WHERE status IN ('queued', 'running')"))
            logger.info("Cleared all previous queued/running trace jobs on startup")
    except Exception as exc:
        logger.warning("Failed to clear previous trace jobs on startup: %s", exc)
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

    # ── Global 500 handler ────────────────────────────────────
    # Starlette's CORSMiddleware does NOT add CORS headers to unhandled
    # exception responses (500s). This causes browsers to report a CORS error
    # instead of the real server error, masking the root cause. This handler
    # injects the correct Access-Control-Allow-Origin on every 500 so browsers
    # (and devtools) can surface the real error message.
    @app.exception_handler(Exception)
    async def _global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception", path=request.url.path, exc_info=exc)
        origin = request.headers.get("origin", "")
        headers: dict[str, str] = {}
        if origin and _is_allowed_origin(origin):
            headers["Access-Control-Allow-Origin"] = origin
            headers["Access-Control-Allow-Credentials"] = "true"
            headers["Vary"] = "Origin"
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
            headers=headers,
        )

    # ── CORS ─────────────────────────────────────────────────────
    # Browsers reject allow_credentials=True when the origin is a wildcard.
    # Origins must be listed explicitly. Add more via the CORS_ORIGINS env var
    # (comma-separated). Deployed hosting domains are matched via regex.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_get_allowed_origins(),
        allow_origin_regex=r"https://.*\.(vercel\.app|render\.com|railway\.app)",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Temporarily disabled for Hackathon to fix CORS/Connectivity ──
    # app.add_middleware(AuditMiddleware)
    # app.add_middleware(SecurityHeadersMiddleware)

    # ── Rate limiter (slowapi) ────────────────────────────────
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(SlowAPIMiddleware)

    # ── Routers ───────────────────────────────────────────────
    from app.api.v1 import router as api_v1_router  # noqa: PLC0415

    app.include_router(api_v1_router)

    # ── Health & root endpoints ───────────────────────────────
    @app.get("/", tags=["health"])
    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok", "service": "Blockchain VASP Attribution Engine"}

    return app


app = create_app()
