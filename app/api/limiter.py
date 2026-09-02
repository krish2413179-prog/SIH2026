"""slowapi rate limiter instance.

Shared across the app so all routes use the same Redis-backed limiter.
Key function: per authenticated user_id (falls back to IP for anonymous).
"""

from __future__ import annotations

from starlette.requests import Request
from slowapi import Limiter


def _get_rate_limit_key(request: Request) -> str:
    """Return the rate-limit key for the current request.

    Uses the authenticated user_id from request.state if available
    (set by auth middleware), otherwise falls back to client IP.
    """
    user_id: str | None = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    # Fallback to IP — pre-auth endpoints (login, health)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_get_rate_limit_key)
