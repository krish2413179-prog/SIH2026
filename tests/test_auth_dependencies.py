"""Unit tests for app/auth/dependencies.py — RBAC FastAPI dependencies.

Tests cover:
- ROLE_HIERARCHY ordering (admin > supervisor > investigator)
- require_role factory raises ValueError for unknown roles
- require_role dependency raises HTTP 403 for insufficient roles
- require_role dependency passes for sufficient roles
- get_current_user raises HTTP 401 for invalid/expired tokens
- get_current_user raises HTTP 401 when user not found in DB
- Convenience aliases map to correct minimum roles
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.auth.dependencies import (
    ROLE_HIERARCHY,
    require_admin,
    require_investigator,
    require_role,
    require_supervisor,
)
from app.auth.models import User, UserRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: UserRole) -> User:
    """Return a minimal User mock with the given role."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = f"{role.value}@example.com"
    user.role = role
    return user


# ---------------------------------------------------------------------------
# ROLE_HIERARCHY tests
# ---------------------------------------------------------------------------


class TestRoleHierarchy:
    def test_admin_has_highest_rank(self):
        assert ROLE_HIERARCHY["admin"] > ROLE_HIERARCHY["supervisor"]

    def test_supervisor_outranks_investigator(self):
        assert ROLE_HIERARCHY["supervisor"] > ROLE_HIERARCHY["investigator"]

    def test_investigator_has_lowest_rank(self):
        assert ROLE_HIERARCHY["investigator"] == min(ROLE_HIERARCHY.values())

    def test_all_three_roles_present(self):
        assert set(ROLE_HIERARCHY.keys()) == {"investigator", "supervisor", "admin"}


# ---------------------------------------------------------------------------
# require_role factory tests
# ---------------------------------------------------------------------------


class TestRequireRoleFactory:
    def test_unknown_role_raises_value_error(self):
        with pytest.raises(ValueError, match="unknown role"):
            require_role("god")

    def test_returns_callable_for_valid_role(self):
        dep = require_role("investigator")
        assert callable(dep)

    def test_dependency_has_descriptive_name(self):
        dep = require_role("supervisor")
        assert dep.__name__ == "require_supervisor"


# ---------------------------------------------------------------------------
# require_role dependency behaviour tests
# ---------------------------------------------------------------------------


class TestRequireRoleDependency:
    """Test the inner async dependency returned by require_role."""

    @pytest.mark.asyncio
    async def test_investigator_passes_investigator_gate(self):
        dep = require_role("investigator")
        user = _make_user(UserRole.investigator)
        result = await dep(current_user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_supervisor_passes_investigator_gate(self):
        dep = require_role("investigator")
        user = _make_user(UserRole.supervisor)
        result = await dep(current_user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_admin_passes_investigator_gate(self):
        dep = require_role("investigator")
        user = _make_user(UserRole.admin)
        result = await dep(current_user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_investigator_blocked_by_supervisor_gate(self):
        from fastapi import HTTPException

        dep = require_role("supervisor")
        user = _make_user(UserRole.investigator)
        with pytest.raises(HTTPException) as exc_info:
            await dep(current_user=user)
        assert exc_info.value.status_code == 403
        assert "investigator" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_investigator_blocked_by_admin_gate(self):
        from fastapi import HTTPException

        dep = require_role("admin")
        user = _make_user(UserRole.investigator)
        with pytest.raises(HTTPException) as exc_info:
            await dep(current_user=user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_supervisor_blocked_by_admin_gate(self):
        from fastapi import HTTPException

        dep = require_role("admin")
        user = _make_user(UserRole.supervisor)
        with pytest.raises(HTTPException) as exc_info:
            await dep(current_user=user)
        assert exc_info.value.status_code == 403
        assert "supervisor" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_supervisor_passes_supervisor_gate(self):
        dep = require_role("supervisor")
        user = _make_user(UserRole.supervisor)
        result = await dep(current_user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_admin_passes_admin_gate(self):
        dep = require_role("admin")
        user = _make_user(UserRole.admin)
        result = await dep(current_user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_403_detail_message_format(self):
        """Error message must include the current user's role name."""
        from fastapi import HTTPException

        dep = require_role("admin")
        user = _make_user(UserRole.investigator)
        with pytest.raises(HTTPException) as exc_info:
            await dep(current_user=user)
        assert exc_info.value.detail == "Action not permitted for role investigator"


# ---------------------------------------------------------------------------
# Convenience alias tests
# ---------------------------------------------------------------------------


class TestConvenienceAliases:
    @pytest.mark.asyncio
    async def test_require_investigator_allows_investigator(self):
        user = _make_user(UserRole.investigator)
        result = await require_investigator(current_user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_require_supervisor_blocks_investigator(self):
        from fastapi import HTTPException

        user = _make_user(UserRole.investigator)
        with pytest.raises(HTTPException) as exc_info:
            await require_supervisor(current_user=user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_require_admin_blocks_supervisor(self):
        from fastapi import HTTPException

        user = _make_user(UserRole.supervisor)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(current_user=user)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_require_admin_allows_admin(self):
        user = _make_user(UserRole.admin)
        result = await require_admin(current_user=user)
        assert result is user


# ---------------------------------------------------------------------------
# get_current_user tests
# ---------------------------------------------------------------------------


class TestGetCurrentUser:
    """Tests for the get_current_user dependency using mocked DB and tokens."""

    @pytest.mark.asyncio
    async def test_raises_401_on_invalid_token(self):
        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials

        from app.auth.dependencies import get_current_user

        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="totally.invalid.token"
        )
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, db=db)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Token invalid or expired"

    @pytest.mark.asyncio
    async def test_raises_401_when_user_not_found(self):
        """Valid token but user deleted from DB should return 401."""
        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials

        from app.auth.dependencies import get_current_user
        from app.auth.tokens import create_token_pair

        user_id = str(uuid.uuid4())
        tokens = create_token_pair(user_id, "investigator")
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=tokens.access_token
        )

        # Simulate DB returning no user
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, db=db)

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_user_for_valid_token(self):
        """Valid token + existing user should return the User object."""
        from fastapi.security import HTTPAuthorizationCredentials

        from app.auth.dependencies import get_current_user
        from app.auth.tokens import create_token_pair

        user_id = str(uuid.uuid4())
        tokens = create_token_pair(user_id, "investigator")
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=tokens.access_token
        )

        expected_user = _make_user(UserRole.investigator)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = expected_user
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        result = await get_current_user(credentials=credentials, db=db)
        assert result is expected_user

    @pytest.mark.asyncio
    async def test_raises_401_for_non_uuid_sub_claim(self):
        """Tokens where 'sub' is not a valid UUID should return 401."""
        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials

        from app.auth.dependencies import get_current_user
        from app.auth.tokens import create_token_pair

        # Create a token with a non-UUID sub
        tokens = create_token_pair("not-a-uuid", "investigator")
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=tokens.access_token
        )
        db = AsyncMock()

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, db=db)

        assert exc_info.value.status_code == 401
