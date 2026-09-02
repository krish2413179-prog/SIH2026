"""FastAPI auth endpoints.

Implements:
- POST /auth/login   — credential login, issues token pair (Req 1.1, 1.2)
- POST /auth/refresh — refresh access token (Req 1.2)
- POST /auth/logout  — invalidate session, requires Bearer token (Req 1.1)

All three endpoints write an AuditLogEntry as a fire-and-forget background
task so that audit failures never block the HTTP response (Req 16.1).

Requirements: 1.1, 1.2, 16.1, 16.6
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction, AuditLogEntry
from app.auth.dependencies import require_investigator
from app.auth.models import User
from app.auth.schemas import FirebaseGoogleLoginRequest, LoginRequest, RefreshRequest, TokenPair
from app.auth.service import authenticate_user
from app.auth.tokens import create_token_pair, refresh_access_token, verify_token
from app.db.session import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Bearer scheme used for the logout endpoint only
_bearer_scheme = HTTPBearer(auto_error=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_source_ip(request: Request) -> str:
    """Extract the best-effort client IP from the request."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _write_audit_log(
    db: AsyncSession,
    action_type: AuditAction,
    source_ip: str,
    actor_user_id: str | None = None,
    session_id: str | None = None,
) -> None:
    """Insert an AuditLogEntry row. Errors are logged but not re-raised."""
    try:
        entry = AuditLogEntry(
            actor_user_id=actor_user_id,
            action_type=action_type,
            resource_type="auth",
            resource_id=None,
            source_ip=source_ip,
            session_id=session_id,
        )
        db.add(entry)
        await db.commit()
    except Exception:
        logger.exception(
            "Audit log write failed",
            action=action_type,
            actor=actor_user_id,
        )


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------


@router.post(
    "/login",
    response_model=TokenPair,
    status_code=status.HTTP_200_OK,
    summary="Authenticate with email + password and receive a JWT token pair",
)
async def login(
    body: LoginRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    """Exchange credentials for an access + refresh token pair."""
    user: User = await authenticate_user(body.email, body.password, db)

    pair: TokenPair = create_token_pair(str(user.id), user.role.value)

    # Extract session_id (jti) from the newly issued access token for audit
    # verify_token requires a DB session for key lookup; use try/except on HTTPException
    session_id: str | None = None
    try:
        access_payload = await verify_token(pair.access_token, db)
        session_id = access_payload.get("jti")
    except HTTPException:
        pass

    source_ip = _get_source_ip(request)

    background_tasks.add_task(
        _write_audit_log,
        db,
        AuditAction.user_login,
        source_ip,
        str(user.id),
        session_id,
    )

    return pair


# ---------------------------------------------------------------------------
# POST /auth/firebase-google
# ---------------------------------------------------------------------------


@router.post(
    "/firebase-google",
    response_model=TokenPair,
    status_code=status.HTTP_200_OK,
    summary="Authenticate via Firebase Google sign-in and receive JWT token pair",
)
async def firebase_google_login(
    body: FirebaseGoogleLoginRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    """Exchange Firebase Google token for application JWT pair."""
    from app.auth.service import authenticate_or_create_firebase_user

    user: User = await authenticate_or_create_firebase_user(
        body.id_token,
        body.email,
        body.display_name,
        db,
    )

    pair: TokenPair = create_token_pair(str(user.id), user.role.value)

    session_id: str | None = None
    try:
        access_payload = await verify_token(pair.access_token, db)
        session_id = access_payload.get("jti")
    except HTTPException:
        pass

    source_ip = _get_source_ip(request)

    background_tasks.add_task(
        _write_audit_log,
        db,
        AuditAction.user_login,
        source_ip,
        str(user.id),
        session_id,
    )

    return pair


# ---------------------------------------------------------------------------
# POST /auth/refresh
# ---------------------------------------------------------------------------


@router.post(
    "/refresh",
    response_model=TokenPair,
    status_code=status.HTTP_200_OK,
    summary="Exchange a refresh token for a new access token",
)
async def refresh(
    body: RefreshRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    """Issue a new TokenPair from a valid refresh token."""
    # refresh_access_token raises HTTPException(401) on failure
    new_pair: TokenPair = await refresh_access_token(body.refresh_token, db)

    session_id: str | None = None
    try:
        access_payload = await verify_token(new_pair.access_token, db)
        session_id = access_payload.get("jti")
    except HTTPException:
        pass

    source_ip = _get_source_ip(request)

    background_tasks.add_task(
        _write_audit_log,
        db,
        AuditAction.token_refresh,
        source_ip,
        None,
        session_id,
    )

    return new_pair


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Invalidate the current Bearer session",
)
async def logout(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_investigator),
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Log out the authenticated user."""
    jti: str | None = None
    try:
        payload = await verify_token(credentials.credentials, db)
        jti = payload.get("jti")
    except HTTPException:
        pass

    source_ip = _get_source_ip(request)

    background_tasks.add_task(
        _write_audit_log,
        db,
        AuditAction.user_logout,
        source_ip,
        str(current_user.id),
        jti,
    )

    return {"message": "Logged out"}
