"""Unit tests for app.auth.service — authenticate_user and pwd_context.

Requirements: 1.1, 1.2, 16.1, 16.6
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import bcrypt as _bcrypt_lib
import pytest

from fastapi import HTTPException

from app.auth.service import authenticate_user, pwd_context, _MAX_FAILED_ATTEMPTS, _LOCKOUT_DURATION_MINUTES
from app.auth.models import User, UserRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash_password(password: str) -> str:
    """Hash a password using bcrypt directly (avoids passlib compat noise)."""
    hashed: bytes = _bcrypt_lib.hashpw(password.encode(), _bcrypt_lib.gensalt(rounds=12))
    return hashed.decode()


def _make_user(
    *,
    email: str = "user@example.com",
    password: str = "correct-password",
    failed_attempts: int = 0,
    locked_until: datetime | None = None,
    role: UserRole = UserRole.investigator,
) -> MagicMock:
    """Build a mock User with a real bcrypt hash for ``password``."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = email
    user.password_hash = _hash_password(password)
    # Set role as the actual UserRole enum (not a spec=User MagicMock attribute)
    user.role = role
    user.failed_login_attempts = failed_attempts
    user.locked_until = locked_until
    return user


def _make_db(user: MagicMock | None) -> AsyncMock:
    """Build a minimal AsyncSession mock returning ``user`` on first execute."""
    db = AsyncMock()

    async def _execute(stmt, *args, **kwargs):
        result = MagicMock()
        result.scalars.return_value.first.return_value = user
        return result

    db.execute.side_effect = _execute
    db.commit = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# pwd_context tests
# ---------------------------------------------------------------------------


class TestPwdContext:
    def test_hash_and_verify_roundtrip(self):
        """pwd_context can verify a hash it created."""
        hashed = _hash_password("my-secret-password")
        # verify using pwd_context (which uses bcrypt internally)
        assert pwd_context.verify("my-secret-password", hashed)

    def test_wrong_password_fails_verify(self):
        hashed = _hash_password("correct-password")
        assert not pwd_context.verify("wrong-password", hashed)

    def test_uses_bcrypt_scheme(self):
        hashed = _hash_password("test-pw")
        # bcrypt hashes start with $2b$ or $2y$
        assert hashed.startswith("$2b$") or hashed.startswith("$2y$")

    def test_minimum_rounds_12(self):
        hashed = _hash_password("test-pw")
        # bcrypt hash encodes cost factor: $2b$<rounds>$...
        parts = hashed.split("$")
        rounds = int(parts[2])
        assert rounds >= 12


# ---------------------------------------------------------------------------
# authenticate_user — success path
# ---------------------------------------------------------------------------


class TestAuthenticateUserSuccess:
    @pytest.mark.asyncio
    async def test_returns_user_on_valid_credentials(self):
        user = _make_user(password="valid-pass")
        db = _make_db(user)

        result = await authenticate_user("user@example.com", "valid-pass", db)

        assert result is user

    @pytest.mark.asyncio
    async def test_resets_failed_attempts_on_success(self):
        user = _make_user(password="valid-pass", failed_attempts=3)
        db = _make_db(user)

        await authenticate_user("user@example.com", "valid-pass", db)

        assert user.failed_login_attempts == 0

    @pytest.mark.asyncio
    async def test_clears_locked_until_on_success(self):
        # Lock in the past (expired lock)
        past = datetime.now(tz=timezone.utc) - timedelta(minutes=1)
        user = _make_user(password="valid-pass", locked_until=past)
        db = _make_db(user)

        result = await authenticate_user("user@example.com", "valid-pass", db)

        assert result is user
        assert user.locked_until is None

    @pytest.mark.asyncio
    async def test_commits_on_success(self):
        user = _make_user(password="valid-pass")
        db = _make_db(user)

        await authenticate_user("user@example.com", "valid-pass", db)

        db.commit.assert_called()


# ---------------------------------------------------------------------------
# authenticate_user — user not found
# ---------------------------------------------------------------------------


class TestAuthenticateUserNotFound:
    @pytest.mark.asyncio
    async def test_missing_user_raises_401(self):
        db = _make_db(None)

        with pytest.raises(HTTPException) as exc_info:
            await authenticate_user("ghost@example.com", "any-password", db)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid credentials"

    @pytest.mark.asyncio
    async def test_missing_user_includes_www_authenticate_header(self):
        db = _make_db(None)

        with pytest.raises(HTTPException) as exc_info:
            await authenticate_user("ghost@example.com", "any-password", db)

        assert "WWW-Authenticate" in exc_info.value.headers


# ---------------------------------------------------------------------------
# authenticate_user — wrong password / account lockout (Req 16.6)
# ---------------------------------------------------------------------------


class TestAuthenticateUserWrongPassword:
    @pytest.mark.asyncio
    async def test_wrong_password_raises_401(self):
        user = _make_user(password="correct")
        db = _make_db(user)

        with pytest.raises(HTTPException) as exc_info:
            await authenticate_user("user@example.com", "wrong", db)

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid credentials"

    @pytest.mark.asyncio
    async def test_wrong_password_increments_failed_attempts(self):
        user = _make_user(password="correct", failed_attempts=0)
        db = _make_db(user)

        with pytest.raises(HTTPException):
            await authenticate_user("user@example.com", "wrong", db)

        assert user.failed_login_attempts == 1

    @pytest.mark.asyncio
    async def test_fourth_failure_does_not_lock(self):
        user = _make_user(password="correct", failed_attempts=_MAX_FAILED_ATTEMPTS - 2)
        db = _make_db(user)

        with pytest.raises(HTTPException):
            await authenticate_user("user@example.com", "wrong", db)

        # Should now be at 4 attempts — not locked yet
        assert user.failed_login_attempts == _MAX_FAILED_ATTEMPTS - 1
        assert user.locked_until is None

    @pytest.mark.asyncio
    async def test_fifth_failure_locks_account(self):
        user = _make_user(password="correct", failed_attempts=_MAX_FAILED_ATTEMPTS - 1)
        db = _make_db(user)

        before = datetime.now(tz=timezone.utc)

        with pytest.raises(HTTPException):
            await authenticate_user("user@example.com", "wrong", db)

        after = datetime.now(tz=timezone.utc)

        # Account must be locked
        assert user.locked_until is not None
        locked = user.locked_until
        if locked.tzinfo is None:
            locked = locked.replace(tzinfo=timezone.utc)
        expected_min = before + timedelta(minutes=_LOCKOUT_DURATION_MINUTES - 1)
        expected_max = after + timedelta(minutes=_LOCKOUT_DURATION_MINUTES + 1)
        assert expected_min <= locked <= expected_max

    @pytest.mark.asyncio
    async def test_fifth_failure_resets_attempts_counter_to_zero(self):
        user = _make_user(password="correct", failed_attempts=_MAX_FAILED_ATTEMPTS - 1)
        db = _make_db(user)

        with pytest.raises(HTTPException):
            await authenticate_user("user@example.com", "wrong", db)

        assert user.failed_login_attempts == 0

    @pytest.mark.asyncio
    async def test_commits_after_failed_attempt(self):
        user = _make_user(password="correct", failed_attempts=0)
        db = _make_db(user)

        with pytest.raises(HTTPException):
            await authenticate_user("user@example.com", "wrong", db)

        db.commit.assert_called()


# ---------------------------------------------------------------------------
# authenticate_user — account locked (Req 16.6)
# ---------------------------------------------------------------------------


class TestAuthenticateUserLocked:
    @pytest.mark.asyncio
    async def test_locked_account_raises_403(self):
        future_lock = datetime.now(tz=timezone.utc) + timedelta(minutes=10)
        user = _make_user(password="correct", locked_until=future_lock)
        db = _make_db(user)

        with pytest.raises(HTTPException) as exc_info:
            await authenticate_user("user@example.com", "correct", db)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_locked_message_contains_unlock_time(self):
        future_lock = datetime.now(tz=timezone.utc) + timedelta(minutes=10)
        user = _make_user(password="correct", locked_until=future_lock)
        db = _make_db(user)

        with pytest.raises(HTTPException) as exc_info:
            await authenticate_user("user@example.com", "correct", db)

        assert "Account locked" in exc_info.value.detail
        assert "Try again after" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_expired_lock_allows_login(self):
        """A lock that has already passed should be cleared on the next attempt."""
        past_lock = datetime.now(tz=timezone.utc) - timedelta(seconds=1)
        user = _make_user(password="correct", locked_until=past_lock)
        db = _make_db(user)

        result = await authenticate_user("user@example.com", "correct", db)

        assert result is user
        assert user.locked_until is None

    @pytest.mark.asyncio
    async def test_naive_locked_until_treated_as_utc(self):
        """Naive datetimes from the DB are treated as UTC."""
        future_naive = datetime.now() + timedelta(minutes=10)  # naive
        user = _make_user(password="correct", locked_until=future_naive)
        db = _make_db(user)

        with pytest.raises(HTTPException) as exc_info:
            await authenticate_user("user@example.com", "correct", db)

        assert exc_info.value.status_code == 403
