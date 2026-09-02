"""Unit tests for app.auth.tokens — token creation, verification, and refresh.

Requirements: 1.1, 1.2, 1.3, 16.7
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from jose import jwt

from app.auth.schemas import TokenPair
from app.auth.tokens import _ALGORITHM, create_token_pair, refresh_access_token, verify_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SECRET = "super-secret-test-key-at-least-32-chars"
USER_ID = str(uuid.uuid4())
ROLE = "investigator"


def _make_jwt_key(secret: str = SECRET, is_current: bool = True, valid_until: datetime | None = None) -> MagicMock:
    """Build a mock JWTKey row."""
    key = MagicMock()
    key.key_value = secret
    key.is_current = is_current
    key.valid_until = valid_until
    return key


def _make_user(user_id: str = USER_ID, role: str = ROLE) -> MagicMock:
    """Build a mock User row."""
    user = MagicMock()
    user.id = user_id
    user.role = MagicMock()
    user.role.value = role
    return user


def _make_db(keys: list[Any], user: Any = None, current_key: Any = None) -> AsyncMock:
    """Build a minimal AsyncSession mock that returns ``keys`` for the first
    execute call (verify_token) and optionally ``user`` + ``current_key``
    for subsequent calls (refresh_access_token)."""
    db = AsyncMock()
    call_count = 0

    async def execute_side_effect(stmt, *args, **kwargs):
        nonlocal call_count
        result = MagicMock()
        if call_count == 0:
            # First call — return active keys list
            result.scalars.return_value.all.return_value = keys
        elif call_count == 1:
            # Second call — return user lookup
            result.scalar_one_or_none.return_value = user
        else:
            # Third call — return current signing key
            result.scalar_one_or_none.return_value = current_key
        call_count += 1
        return result

    db.execute = execute_side_effect
    return db


# ---------------------------------------------------------------------------
# create_token_pair tests
# ---------------------------------------------------------------------------


class TestCreateTokenPair:
    def test_returns_token_pair_instance(self):
        pair = create_token_pair(USER_ID, ROLE, SECRET)
        assert isinstance(pair, TokenPair)
        assert pair.token_type == "bearer"

    def test_access_token_payload(self):
        pair = create_token_pair(USER_ID, ROLE, SECRET)
        payload = jwt.decode(pair.access_token, SECRET, algorithms=[_ALGORITHM])
        assert payload["sub"] == USER_ID
        assert payload["role"] == ROLE
        assert payload["type"] == "access"
        assert "jti" in payload
        assert "iat" in payload
        assert "exp" in payload

    def test_refresh_token_payload(self):
        pair = create_token_pair(USER_ID, ROLE, SECRET)
        payload = jwt.decode(pair.refresh_token, SECRET, algorithms=[_ALGORITHM])
        assert payload["sub"] == USER_ID
        assert payload["type"] == "refresh"
        assert "jti" in payload

    def test_access_token_default_expiry_is_8_hours(self):
        before = datetime.now(tz=timezone.utc)
        pair = create_token_pair(USER_ID, ROLE, SECRET)
        payload = jwt.decode(pair.access_token, SECRET, algorithms=[_ALGORITHM])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        after = datetime.now(tz=timezone.utc)
        assert before + timedelta(hours=7, minutes=59) <= exp <= after + timedelta(hours=8, seconds=5)

    def test_refresh_token_expiry_is_30_days(self):
        before = datetime.now(tz=timezone.utc)
        pair = create_token_pair(USER_ID, ROLE, SECRET)
        payload = jwt.decode(pair.refresh_token, SECRET, algorithms=[_ALGORITHM])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        after = datetime.now(tz=timezone.utc)
        assert before + timedelta(days=29, hours=23) <= exp <= after + timedelta(days=30, seconds=5)

    def test_custom_expiry_hours(self):
        before = datetime.now(tz=timezone.utc)
        pair = create_token_pair(USER_ID, ROLE, SECRET, expiry_hours=2)
        payload = jwt.decode(pair.access_token, SECRET, algorithms=[_ALGORITHM])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        after = datetime.now(tz=timezone.utc)
        assert before + timedelta(hours=1, minutes=59) <= exp <= after + timedelta(hours=2, seconds=5)

    def test_each_call_produces_unique_jtis(self):
        pair1 = create_token_pair(USER_ID, ROLE, SECRET)
        pair2 = create_token_pair(USER_ID, ROLE, SECRET)
        p1 = jwt.decode(pair1.access_token, SECRET, algorithms=[_ALGORITHM])
        p2 = jwt.decode(pair2.access_token, SECRET, algorithms=[_ALGORITHM])
        assert p1["jti"] != p2["jti"]

    def test_access_and_refresh_jtis_are_different(self):
        pair = create_token_pair(USER_ID, ROLE, SECRET)
        access_payload = jwt.decode(pair.access_token, SECRET, algorithms=[_ALGORITHM])
        refresh_payload = jwt.decode(pair.refresh_token, SECRET, algorithms=[_ALGORITHM])
        assert access_payload["jti"] != refresh_payload["jti"]

    def test_different_secrets_produce_unverifiable_tokens(self):
        pair = create_token_pair(USER_ID, ROLE, SECRET)
        with pytest.raises(Exception):
            jwt.decode(pair.access_token, "wrong-secret", algorithms=[_ALGORITHM])


# ---------------------------------------------------------------------------
# verify_token tests
# ---------------------------------------------------------------------------


class TestVerifyToken:
    @pytest.mark.asyncio
    async def test_valid_token_returns_payload(self):
        pair = create_token_pair(USER_ID, ROLE, SECRET)
        key = _make_jwt_key(SECRET)
        db = _make_db([key])

        payload = await verify_token(pair.access_token, db)
        assert payload["sub"] == USER_ID
        assert payload["role"] == ROLE

    @pytest.mark.asyncio
    async def test_no_active_keys_raises_401(self):
        pair = create_token_pair(USER_ID, ROLE, SECRET)
        db = _make_db([])  # no keys

        with pytest.raises(HTTPException) as exc_info:
            await verify_token(pair.access_token, db)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_signature_raises_401(self):
        pair = create_token_pair(USER_ID, ROLE, SECRET)
        key = _make_jwt_key("completely-different-secret-key-xyz")
        db = _make_db([key])

        with pytest.raises(HTTPException) as exc_info:
            await verify_token(pair.access_token, db)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_token_raises_401(self):
        # Create a token that's already expired
        now = datetime.now(tz=timezone.utc)
        payload: dict = {
            "sub": USER_ID,
            "role": ROLE,
            "type": "access",
            "iat": now - timedelta(hours=10),
            "exp": now - timedelta(hours=2),  # expired 2 hours ago
            "jti": str(uuid.uuid4()),
        }
        expired_token = jwt.encode(payload, SECRET, algorithm=_ALGORITHM)
        key = _make_jwt_key(SECRET)
        db = _make_db([key])

        with pytest.raises(HTTPException) as exc_info:
            await verify_token(expired_token, db)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_tries_multiple_keys_and_succeeds_on_second(self):
        """Key rotation: first key is wrong, second key is correct."""
        pair = create_token_pair(USER_ID, ROLE, SECRET)
        wrong_key = _make_jwt_key("wrong-key-but-not-expired-xxxxxxxxx")
        right_key = _make_jwt_key(SECRET)
        db = _make_db([wrong_key, right_key])

        payload = await verify_token(pair.access_token, db)
        assert payload["sub"] == USER_ID

    @pytest.mark.asyncio
    async def test_tampered_token_raises_401(self):
        pair = create_token_pair(USER_ID, ROLE, SECRET)
        # Tamper with the token body
        parts = pair.access_token.split(".")
        tampered = parts[0] + "." + parts[1] + "TAMPERED." + parts[2]
        key = _make_jwt_key(SECRET)
        db = _make_db([key])

        with pytest.raises(HTTPException) as exc_info:
            await verify_token(tampered, db)
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# refresh_access_token tests
# ---------------------------------------------------------------------------


class TestRefreshAccessToken:
    @pytest.mark.asyncio
    async def test_valid_refresh_token_returns_new_pair(self):
        pair = create_token_pair(USER_ID, ROLE, SECRET)
        key = _make_jwt_key(SECRET)
        user = _make_user()
        db = _make_db([key], user=user, current_key=key)

        new_pair = await refresh_access_token(pair.refresh_token, db)
        assert isinstance(new_pair, TokenPair)
        assert new_pair.token_type == "bearer"

    @pytest.mark.asyncio
    async def test_access_token_rejected_as_refresh(self):
        """Passing an access token (type=access) to refresh must be rejected."""
        pair = create_token_pair(USER_ID, ROLE, SECRET)
        key = _make_jwt_key(SECRET)
        db = _make_db([key])

        with pytest.raises(HTTPException) as exc_info:
            await refresh_access_token(pair.access_token, db)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_nonexistent_user_raises_401(self):
        pair = create_token_pair(USER_ID, ROLE, SECRET)
        key = _make_jwt_key(SECRET)
        db = _make_db([key], user=None)  # user not found

        with pytest.raises(HTTPException) as exc_info:
            await refresh_access_token(pair.refresh_token, db)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_refresh_token_raises_401(self):
        key = _make_jwt_key(SECRET)
        db = _make_db([key])

        with pytest.raises(HTTPException) as exc_info:
            await refresh_access_token("not.a.valid.token", db)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_new_pair_preserves_user_role(self):
        pair = create_token_pair(USER_ID, "supervisor", SECRET)
        key = _make_jwt_key(SECRET)
        user = _make_user(role="supervisor")
        db = _make_db([key], user=user, current_key=key)

        new_pair = await refresh_access_token(pair.refresh_token, db)
        new_payload = jwt.decode(new_pair.access_token, SECRET, algorithms=[_ALGORITHM])
        assert new_payload["role"] == "supervisor"

    @pytest.mark.asyncio
    async def test_new_pair_has_fresh_jtis(self):
        pair = create_token_pair(USER_ID, ROLE, SECRET)
        old_payload = jwt.decode(pair.access_token, SECRET, algorithms=[_ALGORITHM])

        key = _make_jwt_key(SECRET)
        user = _make_user()
        db = _make_db([key], user=user, current_key=key)

        new_pair = await refresh_access_token(pair.refresh_token, db)
        new_payload = jwt.decode(new_pair.access_token, SECRET, algorithms=[_ALGORITHM])
        assert new_payload["jti"] != old_payload["jti"]
