"""Shared pytest fixtures for the test suite.

Provides:
- async_client: httpx AsyncClient wired to the FastAPI app
- db: async SQLAlchemy session against a test DB
- redis_client: fakeredis async client
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Set test environment variables before importing app modules
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-not-for-production-32b")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-key-not-for-production-32byte")
os.environ.setdefault("DB_ENCRYPTION_KEY", "test-encryption-key-not-for-production")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/vasp_engine_test")
os.environ.setdefault("DATABASE_SYNC_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/vasp_engine_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture
async def async_client() -> AsyncClient:
    """Async test client for FastAPI app."""
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client
