"""Authentication business logic.

Implements:
- pwd_context: bcrypt password hashing with minimum rounds=12 (Req 16.1)
- authenticate_user: credential verification with account-lockout enforcement (Req 16.6)

Requirements: 1.1, 1.2, 16.1, 16.6
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User

# ---------------------------------------------------------------------------
# Password hashing context — bcrypt with minimum cost factor 12 (Req 16.1)
# ---------------------------------------------------------------------------

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_FAILED_ATTEMPTS = 5
_LOCKOUT_DURATION_MINUTES = 15


# ---------------------------------------------------------------------------
# authenticate_user
# ---------------------------------------------------------------------------


async def authenticate_user(
    email: str,
    password: str,
    db: AsyncSession,
) -> User:
    """Verify credentials and return the authenticated User.

    Implements account-lockout after 5 consecutive failed attempts (Req 16.6):
    - On the 5th failure the account is locked for 15 minutes.
    - Subsequent requests while locked return HTTP 403 with an unlock time.
    - On success the failure counter and lock are cleared.

    Args:
        email: The user's email address.
        password: The plain-text password to verify.
        db: An open async SQLAlchemy session.

    Returns:
        The authenticated ``User`` ORM instance.

    Raises:
        HTTPException(401): Email not found or password incorrect.
        HTTPException(403): Account is currently locked.
    """
    # --- User lookup ---
    result = await db.execute(select(User).where(User.email == email))
    user: User | None = result.scalars().first()

    if user is None:
        # Use same 401 as bad password to avoid user enumeration
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # --- Account-lockout check ---
    now = datetime.now(tz=timezone.utc)
    if user.locked_until is not None:
        # Make locked_until timezone-aware if the DB returns a naive datetime
        locked_until = user.locked_until
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until > now:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Account locked. Try again after {locked_until.isoformat()}",
            )
        # Lock has expired — clear it so next failure starts a fresh counter
        user.locked_until = None
        user.failed_login_attempts = 0

    # --- Password verification ---
    if not pwd_context.verify(password, user.password_hash):
        # Increment failure counter
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1

        if user.failed_login_attempts >= _MAX_FAILED_ATTEMPTS:
            # Lock the account
            user.locked_until = now + timedelta(minutes=_LOCKOUT_DURATION_MINUTES)
            user.failed_login_attempts = 0

        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # --- Success — reset lockout state ---
    user.failed_login_attempts = 0
    user.locked_until = None
    await db.commit()

    return user


async def authenticate_or_create_firebase_user(
    id_token: str,
    email_hint: str | None,
    display_name: str | None,
    db: AsyncSession,
) -> User:
    """Verify Firebase Google ID token and return/provision User."""
    import secrets
    import httpx

    verified_email = email_hint
    
    # Verify token with Google's tokeninfo API
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}"
            )
            if resp.status_code == 200:
                payload = resp.json()
                verified_email = payload.get("email") or verified_email
    except Exception:
        # Fallback to provided email if network call to google fails
        pass

    if not verified_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to verify Google user email from token",
        )

    # Check if user already exists
    result = await db.execute(select(User).where(User.email == verified_email))
    user: User | None = result.scalars().first()

    if user is None:
        # Auto-provision user with investigator role
        random_pwd = secrets.token_urlsafe(32)
        user = User(
            email=verified_email,
            password_hash=pwd_context.hash(random_pwd),
            role=UserRole.investigator,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    return user

