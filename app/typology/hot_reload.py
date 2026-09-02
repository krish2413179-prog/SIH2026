"""Typology hot-reload: poll Redis version counter, update in-process cache.

Workers poll ``typology_definitions:version`` in Redis every 60 seconds.
When the counter advances, all ``TypologyDefinition`` rows are reloaded from
the database and the in-process cache is replaced atomically.

Requirements: 9.5
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import TypologyDefinition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis key
# ---------------------------------------------------------------------------

TYPOLOGY_VERSION_KEY = "typology_definitions:version"

# ---------------------------------------------------------------------------
# Module-level state (updated in-place by check_and_reload)
# ---------------------------------------------------------------------------

_current_version: int = -1
_definition_cache: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


async def load_definitions_from_db(db: AsyncSession) -> dict[str, Any]:
    """Load all TypologyDefinition rows from the DB.

    Returns:
        Mapping of ``typology_name`` → ``definition_json`` dict for every row
        present in the ``typology_definitions`` table.
    """
    result = await db.execute(select(TypologyDefinition))
    rows = result.scalars().all()
    return {row.typology_name: row.definition_json for row in rows}


async def get_current_version(redis_client) -> int:
    """Return the current typology version counter stored in Redis.

    Returns:
        The integer value of ``typology_definitions:version``, or ``0`` if the
        key does not exist yet.
    """
    raw = await redis_client.get(TYPOLOGY_VERSION_KEY)
    if raw is None:
        return 0
    # The Redis client may return bytes or str depending on decode_responses setting
    return int(raw)


async def check_and_reload(db: AsyncSession, redis_client) -> bool:
    """Compare the Redis version counter to the cached version.

    If the Redis counter is newer, all definitions are reloaded from the DB
    and the in-process ``_definition_cache`` is replaced.

    Args:
        db: An open async SQLAlchemy session.
        redis_client: An async Redis client instance.

    Returns:
        ``True`` if a reload was performed, ``False`` if the cache is already
        up-to-date.
    """
    global _current_version, _definition_cache  # noqa: PLW0603

    remote_version = await get_current_version(redis_client)

    if remote_version <= _current_version:
        return False

    logger.info(
        "Typology definitions changed — reloading from DB "
        "(cached_version=%d, remote_version=%d)",
        _current_version,
        remote_version,
    )

    new_cache = await load_definitions_from_db(db)
    _definition_cache = new_cache
    _current_version = remote_version

    logger.info(
        "Typology definitions reloaded: %d definitions loaded (version=%d)",
        len(_definition_cache),
        _current_version,
    )
    return True


async def start_polling_loop(
    get_db_fn,
    get_redis_fn,
    interval: int = 60,
) -> None:
    """Background coroutine that polls for typology definition changes.

    Calls ``check_and_reload`` every ``interval`` seconds.  Designed to be
    started via ``asyncio.create_task`` in the application lifespan.

    Args:
        get_db_fn: Async callable (or async generator factory) that provides
            an ``AsyncSession``.  If it is an async generator (e.g.
            ``get_db``), it is consumed and properly closed after each poll.
        get_redis_fn: Async callable (or async generator factory) that
            provides an async Redis client.
        interval: Poll interval in seconds (default 60).
    """
    logger.info(
        "Typology hot-reload polling loop started (interval=%ds)", interval
    )

    while True:
        await asyncio.sleep(interval)
        try:
            # Support both plain callables and async generator factories
            db_gen = get_db_fn()
            if hasattr(db_gen, "__anext__"):
                db = await db_gen.__anext__()
            else:
                db = await db_gen  # type: ignore[misc]

            redis_gen = get_redis_fn()
            if hasattr(redis_gen, "__anext__"):
                redis_client = await redis_gen.__anext__()
            else:
                redis_client = await redis_gen  # type: ignore[misc]

            await check_and_reload(db=db, redis_client=redis_client)

            # Close the DB session if it is an async generator
            if hasattr(db_gen, "aclose"):
                await db_gen.aclose()

        except asyncio.CancelledError:
            logger.info("Typology hot-reload polling loop cancelled — shutting down")
            break
        except Exception:
            logger.exception(
                "Typology hot-reload: unhandled error during poll; will retry in %ds",
                interval,
            )


def get_cached_definitions() -> dict[str, Any]:
    """Return the current in-process typology definition cache (read-only view).

    Returns:
        A dict of ``typology_name`` → ``definition_json`` reflecting the most
        recently reloaded state.
    """
    return _definition_cache
