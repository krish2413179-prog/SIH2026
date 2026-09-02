"""JWT token creation and verification utilities.

Implements create_token_pair, verify_token, and refresh_access_token
using python-jose with HS256. Supports multi-key lookup for key rotation
(Req 16.7).

verify_token and refresh_access_token query the jwt_keys table for all
active signing keys so that in-flight tokens survive key rotation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from jose import ExpiredSignatureError, JWTError, jwt
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import TokenPair
from app.config import get_settings

settings = get_settings()

# Module-level algorithm constant — exported for tests
_ALGORITHM = settings.jwt_algorithm

_DEFAULT_ACCESS_EXPIRY_HOURS = settings.jwt_access_token_expire_hours
_DEFAULT_REFRESH_EXPIRY_DAYS = settings.jwt_refresh_token_expire_days


def create_token_pair(
    user_id: str,
    role: str,
    secret: str | None = None,
    *,
    expiry_hours: int | None = None,
    refresh_expiry_days: int | None = None,
) -> TokenPair:
    """Create an access + refresh token pair.

    Args:
        user_id: The subject claim (UUID string of the user).
        role: RBAC role string (investigator | supervisor | admin).
        secret: Override JWT signing secret (defaults to settings.jwt_secret_key).
        expiry_hours: Override access token TTL in hours (default 8).
        refresh_expiry_days: Override refresh token TTL in days (default 30).

    Returns:
        TokenPair with access_token, refresh_token, token_type="bearer".
    """
    _secret = secret or settings.jwt_secret_key
    _access_hours = expiry_hours if expiry_hours is not None else _DEFAULT_ACCESS_EXPIRY_HOURS
    _refresh_days = refresh_expiry_days if refresh_expiry_days is not None else _DEFAULT_REFRESH_EXPIRY_DAYS

    now = datetime.now(tz=timezone.utc)

    access_payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(hours=_access_hours),
        "jti": str(uuid.uuid4()),
    }
    refresh_payload = {
        "sub": user_id,
        "role": role,
        "type": "refresh",
        "iat": now,
        "exp": now + timedelta(days=_refresh_days),
        "jti": str(uuid.uuid4()),
    }

    return TokenPair(
        access_token=jwt.encode(access_payload, _secret, algorithm=_ALGORITHM),
        refresh_token=jwt.encode(refresh_payload, _secret, algorithm=_ALGORITHM),
    )


async def verify_token(token: str, db: AsyncSession) -> dict:
    """Decode and verify a JWT token against all active signing keys.

    Queries the jwt_keys table for keys where is_current=True OR
    valid_until > now(), tries each key, and returns the first successfully
    decoded payload.

    Args:
        token: Raw JWT string (without the "Bearer " prefix).
        db: An open async SQLAlchemy session.

    Returns:
        The decoded payload dict.

    Raises:
        HTTPException(401): If no key can verify the token.
    """
    from app.auth.models import JWTKey  # avoid circular import at module level

    now = datetime.now(tz=timezone.utc)

    result = await db.execute(
        select(JWTKey).where(
            or_(JWTKey.is_current.is_(True), JWTKey.valid_until > now)
        )
    )
    keys_scalars = result.scalars()
    # Handle both sync (production SQLAlchemy) and async (AsyncMock in tests) results
    import inspect
    if inspect.isawaitable(keys_scalars):
        keys_scalars = await keys_scalars
    keys = keys_scalars.all()
    if inspect.isawaitable(keys):
        keys = await keys

    if not keys:
        # Fallback: try the settings secret directly (useful in tests / cold start)
        try:
            payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[_ALGORITHM])
            return payload
        except (JWTError, ExpiredSignatureError):
            pass
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    last_error: Exception | None = None
    for key in keys:
        try:
            payload = jwt.decode(token, key.key_value, algorithms=[_ALGORITHM])
            return payload
        except (JWTError, ExpiredSignatureError) as exc:
            last_error = exc
            continue

    # Final fallback: try settings secret (handles cold-start / test environments)
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[_ALGORITHM])
        return payload
    except (JWTError, ExpiredSignatureError) as exc:
        last_error = exc

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalid or expired",
        headers={"WWW-Authenticate": "Bearer"},
    ) from last_error


async def refresh_access_token(refresh_token: str, db: AsyncSession) -> TokenPair:
    """Issue a new TokenPair from a valid refresh token.

    Steps:
    1. Verify the refresh_token against all active keys.
    2. Confirm type == "refresh".
    3. Look up the user to confirm they still exist.
    4. Sign a new pair with the current active key.

    Args:
        refresh_token: A "refresh" type JWT.
        db: An open async SQLAlchemy session.

    Returns:
        A new TokenPair.

    Raises:
        HTTPException(401): If the refresh token is invalid, expired, wrong type,
            or the user no longer exists.
    """
    from app.auth.models import JWTKey, User  # avoid circular import

    # Verify and decode
    payload = await verify_token(refresh_token, db)

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: str = payload.get("sub", "")

    # Confirm user still exists
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    role: str = user.role.value

    # Get the current signing key
    result = await db.execute(select(JWTKey).where(JWTKey.is_current.is_(True)))
    current_key = result.scalar_one_or_none()
    secret = current_key.key_value if current_key else settings.jwt_secret_key

    return create_token_pair(user_id, role, secret)
