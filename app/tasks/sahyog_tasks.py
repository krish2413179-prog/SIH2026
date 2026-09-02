"""Celery task: submit to SAHYOG Portal with retry.

Uses the same sync-session / asyncio.run bridge pattern as trace_tasks.py.

Requirements: 12.1, 12.3, 16.4
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid

from celery.exceptions import MaxRetriesExceededError

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sync engine helper (mirrors trace_tasks.py)
# ---------------------------------------------------------------------------


def _get_sync_session_factory():
    """Return a sync sessionmaker bound to the sync database engine."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    sync_url = os.environ.get("DATABASE_SYNC_URL")
    if not sync_url:
        from app.config import get_settings
        sync_url = get_settings().database_sync_url

    engine = create_engine(
        sync_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_recycle=3600,
    )
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@celery_app.task(
    name="tasks.sahyog.submit",
    bind=True,
    max_retries=3,
)
def submit_sahyog(self, submission_id: str) -> dict:  # type: ignore[override]
    """Load SAHYOGSubmission, call SAHYOGClient.submit(), update status.

    Steps
    -----
    1. Verify the submission row exists (sync query to avoid async complexity
       for a lightweight existence check).
    2. Delegate to the async ``submit_to_sahyog`` service via ``asyncio.run``,
       which handles loading related records, calling the portal, and updating
       submission status.
    3. On unhandled exception: retry up to ``max_retries`` with a 30 s
       countdown.  After all retries are exhausted the failure is preserved in
       the DB by the service layer.

    Args:
        submission_id: String UUID of the :class:`~app.sahyog.models.SAHYOGSubmission`
            to process.

    Requirements: 12.1, 12.3, 16.4
    """
    sub_uuid = uuid.UUID(submission_id)
    SyncSession = _get_sync_session_factory()

    # Light sync existence check
    with SyncSession() as sync_db:
        from sqlalchemy import select as sync_select
        from app.sahyog.models import SAHYOGSubmission

        row = sync_db.execute(
            sync_select(SAHYOGSubmission).where(SAHYOGSubmission.id == sub_uuid)
        ).scalars().first()

        if row is None:
            logger.error(
                "submit_sahyog: SAHYOGSubmission %s not found — skipping",
                submission_id,
            )
            return {"submission_id": submission_id, "status": "not_found"}

    # Delegate to async service via asyncio.run bridge
    try:
        result = asyncio.run(_run_async_submission(submission_id))
        logger.info(
            "submit_sahyog: submission %s completed — status=%s reference=%s",
            submission_id,
            result.get("status"),
            result.get("portal_reference_number"),
        )
        return result

    except Exception as exc:
        logger.exception(
            "submit_sahyog: submission %s failed with error: %s",
            submission_id,
            exc,
        )
        try:
            raise self.retry(exc=exc, countdown=30)
        except MaxRetriesExceededError:
            logger.error(
                "submit_sahyog: submission %s exhausted all retries — permanently failed",
                submission_id,
            )
            return {"submission_id": submission_id, "status": "failed"}


# ---------------------------------------------------------------------------
# Async bridge helper
# ---------------------------------------------------------------------------


async def _run_async_submission(submission_id: str) -> dict:
    """Run the async SAHYOG submission service using a dedicated async session."""
    from app.db.session import AsyncSessionLocal
    from app.sahyog.service import submit_to_sahyog

    async with AsyncSessionLocal() as async_db:
        try:
            result = await submit_to_sahyog(submission_id=submission_id, db=async_db)
            await async_db.commit()
            return result
        except Exception:
            await async_db.rollback()
            raise
