"""Redis client dependency and utility helpers.

Provides a FastAPI ``Depends``-compatible ``get_redis()`` factory and a
standalone ``get_redis_client()`` for use in non-request contexts (e.g.,
Celery tasks or background threads).

The client is backed by the ``redis.asyncio`` (aioredis-compatible) driver
included in ``redis>=4.2``.

Note: ``decode_responses`` is intentionally ``False`` so that binary payloads
(e.g., ``orjson``-serialised cache entries) are stored and retrieved without
modification.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import redis.asyncio as aioredis

from app.config import get_settings

# Module-level client — created once, reused across all requests.
_client: aioredis.Redis | None = None


def get_redis_client() -> aioredis.Redis:
    """Return (or lazily create) the shared async Redis client.

    Safe to call from outside a FastAPI dependency context (e.g., Celery).
    ``decode_responses=False`` so binary ``orjson`` cache values pass through
    unchanged.
    """
    global _client  # noqa: PLW0603
    if _client is None:
        settings = get_settings()
        _client = aioredis.from_url(
            settings.redis_url,
            decode_responses=False,
            max_connections=20,
        )
    return _client


async def get_redis() -> AsyncIterator[aioredis.Redis]:
    """FastAPI dependency that yields an async Redis client.

    Usage::

        @router.get("/example")
        async def example(redis: aioredis.Redis = Depends(get_redis)):
            ...
    """
    yield get_redis_client()
