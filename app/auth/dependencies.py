"""FastAPI RBAC dependencies — auth bypassed, uses real admin user from DB."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, UserRole
from app.db.session import AsyncSessionLocal

ROLE_HIERARCHY: dict[str, int] = {
    "investigator": 1,
    "supervisor": 2,
    "admin": 3,
}

# Cache the real admin user ID after first lookup
_cached_admin_id: uuid.UUID | None = None
_cached_org_unit_id: uuid.UUID | None = None


async def _get_real_admin() -> tuple[uuid.UUID, uuid.UUID | None]:
    """Fetch the first admin user from the DB and cache their ID."""
    global _cached_admin_id, _cached_org_unit_id
    if _cached_admin_id is not None:
        return _cached_admin_id, _cached_org_unit_id
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(User).where(User.role == UserRole.admin).limit(1)
            )
            user = result.scalars().first()
            if user:
                _cached_admin_id = user.id
                _cached_org_unit_id = user.org_unit_id
                return user.id, user.org_unit_id
    except Exception:
        pass
    # Fallback: return a zero UUID (will fail FK, but at least server starts)
    fallback = uuid.UUID("00000000-0000-0000-0000-000000000001")
    _cached_admin_id = fallback
    return fallback, None


def _make_dummy_user(user_id: uuid.UUID, org_unit_id: uuid.UUID | None):
    user = MagicMock()
    user.id = user_id
    user.email = "admin@lea.gov.in"
    role_mock = MagicMock()
    role_mock.value = "admin"
    user.role = role_mock
    user.org_unit_id = org_unit_id or uuid.UUID("00000000-0000-0000-0000-000000000002")
    user.failed_login_attempts = 0
    user.locked_until = None
    return user


async def get_current_user():
    uid, org_id = await _get_real_admin()
    return _make_dummy_user(uid, org_id)


def require_role(minimum_role: str):
    if minimum_role not in ROLE_HIERARCHY:
        raise ValueError(f"require_role: unknown role {minimum_role!r}.")

    async def _dependency():
        uid, org_id = await _get_real_admin()
        return _make_dummy_user(uid, org_id)

    _dependency.__name__ = f"require_{minimum_role}"
    return _dependency


require_investigator = require_role("investigator")
require_supervisor = require_role("supervisor")
require_admin = require_role("admin")
