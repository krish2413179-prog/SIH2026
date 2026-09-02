"""Pydantic v2 schemas for authentication and token handling.

Requirements: 1.1, 1.2, 1.3, 16.7
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """Credentials submitted to POST /auth/login."""

    email: EmailStr
    password: str = Field(..., min_length=1)


class FirebaseGoogleLoginRequest(BaseModel):
    """Firebase ID token submitted to POST /auth/firebase-google."""

    id_token: str = Field(..., min_length=1)
    email: EmailStr | None = None
    display_name: str | None = None


class TokenPair(BaseModel):
    """Access + refresh token pair returned after successful login or refresh.

    Requirement 1.2 — JWT token pair issued on authentication.
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    """Body for POST /auth/refresh — exchange a refresh token for a new pair."""

    refresh_token: str = Field(..., min_length=1)


class TokenPayload(BaseModel):
    """Decoded JWT payload structure.

    Both access and refresh tokens share these fields; access tokens have
    ``type="access"`` (the default) while refresh tokens have ``type="refresh"``.

    Requirement 1.3 — token payload carries subject, role, and expiry.
    """

    sub: str  # user_id (UUID string)
    role: str  # UserRole value
    iat: int   # issued-at (UNIX timestamp)
    exp: int   # expiry  (UNIX timestamp)
    jti: str   # unique token ID
    type: str = "access"
