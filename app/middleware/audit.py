"""AuditMiddleware — post-response audit logging for mutating requests.

After every successful response, inspects the HTTP method and path to:
  1. Decide whether to write an audit log entry (skip if path is in SKIP_PATHS
     or the method+path pattern doesn't map to a known AuditAction).
  2. Extract the actor's user_id and session jti from the Bearer token
     (best-effort; None on any failure — never blocks the response).
  3. Write an AuditLogEntry row using a fresh, fire-and-forget DB session.

Requirements: 1.9, 14.1, 14.2
"""

from __future__ import annotations

import re
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.audit.models import AuditAction, AuditLogEntry
from app.auth.tokens import verify_token
from app.db.session import AsyncSessionLocal

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Paths that are never audited (infrastructure / auth / docs)
SKIP_PATHS: frozenset[str] = frozenset(
    {
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/auth/login",
        "/auth/refresh",
        "/auth/logout",
    }
)

# HTTP methods that can generate audit entries
MUTATING_METHODS: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# ---------------------------------------------------------------------------
# Path → AuditAction mapping (evaluated in order; first match wins)
# ---------------------------------------------------------------------------

# Each entry: (method, compiled-regex, AuditAction)
_PATH_RULES: list[tuple[str, re.Pattern[str], AuditAction]] = [
    # Case management
    ("POST",   re.compile(r"^/api/v1/cases$"),                        AuditAction.case_created),
    ("PATCH",  re.compile(r"^/api/v1/cases/[^/]+$"),                  AuditAction.case_updated),
    ("DELETE", re.compile(r"^/api/v1/cases/[^/]+$"),                  AuditAction.case_deleted),
    # Wallet submission
    ("POST",   re.compile(r".*/wallets$"),                             AuditAction.wallet_submitted),
    # Report sign / SAHYOG submit (must come BEFORE generic */reports)
    ("POST",   re.compile(r".*/sign$"),                                AuditAction.report_signed),
    ("POST",   re.compile(r".*/submit-sahyog$"),                       AuditAction.sahyog_submitted),
    # Report generation — POST .../reports but NOT sign or submit-sahyog
    ("POST",   re.compile(r".*/reports$"),                             AuditAction.report_generated),
    # VASP management
    ("POST",   re.compile(r"^/api/v1/admin/vasps$"),                   AuditAction.vasp_created),
    ("PATCH",  re.compile(r"^/api/v1/admin/vasps/[^/]+$"),             AuditAction.vasp_updated),
    # User management
    ("POST",   re.compile(r"^/api/v1/admin/users$"),                   AuditAction.user_created),
    ("PATCH",  re.compile(r"^/api/v1/admin/users/[^/]+$"),             AuditAction.user_updated),
]


def _resolve_action(method: str, path: str) -> AuditAction | None:
    """Return the AuditAction for the given method+path, or None to skip."""
    for rule_method, pattern, action in _PATH_RULES:
        if method == rule_method and pattern.match(path):
            return action
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_source_ip(request: Request) -> str:
    """Return the best-effort client IP address."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first (leftmost) address — the original client
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _extract_token_claims(request: Request) -> tuple[uuid.UUID | None, str | None]:
    """Parse the Authorization header and return (user_id, jti) or (None, None).

    Note: verify_token is async and requires a DB session for key lookup.
    The middleware extracts claims via a best-effort JWT decode using the
    settings secret — no DB round-trip. This is sufficient for audit logging.
    """
    from jose import jwt as _jwt, JWTError
    from app.config import get_settings as _get_settings

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, None

    raw_token = auth_header[len("Bearer "):]
    try:
        _settings = _get_settings()
        payload = _jwt.decode(
            raw_token,
            _settings.jwt_secret_key,
            algorithms=[_settings.jwt_algorithm],
        )
        sub = payload.get("sub")
        jti = payload.get("jti")
        actor_id = uuid.UUID(sub) if sub else None
        return actor_id, jti
    except (JWTError, ValueError, AttributeError):
        return None, None


@asynccontextmanager
async def _audit_session() -> AsyncIterator:
    """Yield a fresh AsyncSession for writing the audit entry."""
    async with AsyncSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class AuditMiddleware(BaseHTTPMiddleware):
    """Write an AuditLogEntry after every auditable mutating request.

    Fire-and-forget: audit failures are logged but never surface to the
    caller.  The response has already been sent before this runs.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Always forward the request first — the audit happens post-response
        response = await call_next(request)

        method = request.method.upper()
        path = request.url.path

        # Fast-path: skip non-mutating methods and known skip-paths immediately
        if method not in MUTATING_METHODS or path in SKIP_PATHS:
            return response

        action = _resolve_action(method, path)
        if action is None:
            # No mapping found — skip silently (no "unknown" entries)
            return response

        # Kick off the fire-and-forget audit write without blocking the response
        actor_user_id, session_id = _extract_token_claims(request)
        source_ip = _extract_source_ip(request)

        import asyncio

        async def _safe_write_audit():
            try:
                await self._write_audit_entry(
                    action=action,
                    actor_user_id=actor_user_id,
                    session_id=session_id,
                    source_ip=source_ip,
                    path=path,
                )
            except Exception:
                logger.exception(
                    "audit_write_failed",
                    method=method,
                    path=path,
                    action=action,
                )

        asyncio.create_task(_safe_write_audit())

        return response

    async def _write_audit_entry(
        self,
        *,
        action: AuditAction,
        actor_user_id: uuid.UUID | None,
        session_id: str | None,
        source_ip: str,
        path: str,
    ) -> None:
        """Persist a single AuditLogEntry row using a dedicated session."""
        # Derive a human-readable resource_type from the action name
        resource_type = action.value.split("_")[0]  # e.g. "case", "user", "vasp"

        entry = AuditLogEntry(
            actor_user_id=actor_user_id,
            action_type=action,
            resource_type=resource_type,
            resource_id=None,       # Middleware has no access to the response body
            before_state=None,
            after_state=None,
            source_ip=source_ip,
            session_id=session_id,
        )

        async with _audit_session() as session:
            try:
                session.add(entry)
                await session.commit()
                logger.debug(
                    "audit_entry_written",
                    action=action,
                    actor=str(actor_user_id),
                    path=path,
                )
            except Exception:
                await session.rollback()
                raise
