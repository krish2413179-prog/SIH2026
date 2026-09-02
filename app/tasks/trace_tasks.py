"""Celery task: run a blockchain trace job.

Implements the core worker logic for tracing a wallet address across its
blockchain transaction graph, persisting the result, and updating the
TraceJob lifecycle state.

Requirements: 5.5, 15.4
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

from celery.exceptions import MaxRetriesExceededError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sync engine helper
# ---------------------------------------------------------------------------

def _get_sync_session_factory() -> sessionmaker:
    """Return a sync sessionmaker bound to the sync database engine.

    Prefers the ``DATABASE_SYNC_URL`` environment variable; falls back to
    ``settings.database_sync_url`` from application config.
    """
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
    name="tasks.trace.run_trace",
    bind=True,
    max_retries=3,
)
def run_trace(self, trace_job_id: str) -> None:  # type: ignore[override]
    """Execute a full blockchain trace for the given TraceJob.

    Steps
    -----
    1. Open a synchronous SQLAlchemy session.
    2. Load :class:`~app.graph.models.TraceJob` by *trace_job_id*; set
       ``status='running'`` and ``started_at=now()``, flush.
    3. Obtain a :class:`~app.adapters.base.BlockchainAdapter` for the job's
       chain via :func:`~app.adapters.registry.get_adapter`.
    4. Build the transaction graph using
       :func:`~app.graph.builder.build_graph` (run via ``asyncio.run``).
    5. Persist the graph using
       :func:`~app.graph.persistence.save_graph` (run via ``asyncio.run``
       with a dedicated async session).
    6. Set ``status='completed'``, ``completed_at=now()``,
       ``estimated_pct=100.0``, and commit.
    7. On any unhandled exception: set ``status='failed'``,
       ``completed_at=now()``, commit, then retry with a 30-second countdown.
       After ``max_retries`` exhausted the failure state is preserved.

    Args:
        trace_job_id: String UUID of the :class:`~app.graph.models.TraceJob`
            to process.

    Requirements: 5.5, 15.4
    """
    job_uuid = uuid.UUID(trace_job_id)
    SyncSession: sessionmaker = _get_sync_session_factory()

    with SyncSession() as db:
        try:
            # ----------------------------------------------------------------
            # 1–2. Load job and mark as running
            # ----------------------------------------------------------------
            job = db.execute(
                select(_get_trace_job_model()).where(
                    _get_trace_job_model().id == job_uuid
                )
            ).scalars().first()

            if job is None:
                logger.error("run_trace: TraceJob %s not found — skipping", trace_job_id)
                return

            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            db.flush()
            db.commit()

            # ----------------------------------------------------------------
            # 3. Get blockchain adapter
            # ----------------------------------------------------------------
            from app.adapters.registry import get_adapter
            adapter = get_adapter(job.chain)

            # ----------------------------------------------------------------
            # 4 + 5. Build graph AND save — single asyncio.run() call to avoid
            #        "Event loop is closed" error on Python 3.14 with solo pool
            # ----------------------------------------------------------------
            from app.graph.builder import build_graph

            async def _build_and_save():
                G = await build_graph(
                    seed_address=job.wallet_address,
                    chain=job.chain,
                    adapter=adapter,
                    max_hops=job.max_hops,
                )
                await _save_graph_async(
                    trace_id=job.id,
                    case_id=job.case_id,
                    wallet_address=job.wallet_address,
                    chain=job.chain,
                    G=G,
                )
                return G

            G = asyncio.run(_build_and_save())

            # ----------------------------------------------------------------
            # 6. Mark job as completed
            # ----------------------------------------------------------------
            # Re-query within the same session to get a fresh reference after
            # the async save committed in a different connection.
            with SyncSession() as final_db:
                final_job = final_db.execute(
                    select(_get_trace_job_model()).where(
                        _get_trace_job_model().id == job_uuid
                    )
                ).scalars().first()

                if final_job is not None:
                    final_job.status = "completed"
                    final_job.completed_at = datetime.now(timezone.utc)
                    final_job.estimated_pct = 100.0
                    final_db.commit()

            logger.info(
                "run_trace: TraceJob %s completed successfully "
                "(nodes=%d, edges=%d)",
                trace_job_id,
                G.number_of_nodes(),
                G.number_of_edges(),
            )

        except Exception as exc:
            # ----------------------------------------------------------------
            # 7. Handle failure — mark job failed, then schedule retry
            # ----------------------------------------------------------------
            logger.exception(
                "run_trace: TraceJob %s failed with error: %s",
                trace_job_id,
                exc,
            )

            try:
                with SyncSession() as fail_db:
                    failed_job = fail_db.execute(
                        select(_get_trace_job_model()).where(
                            _get_trace_job_model().id == job_uuid
                        )
                    ).scalars().first()

                    if failed_job is not None:
                        failed_job.status = "failed"
                        failed_job.completed_at = datetime.now(timezone.utc)
                        fail_db.commit()
            except Exception:
                logger.exception(
                    "run_trace: Failed to persist failure state for TraceJob %s",
                    trace_job_id,
                )

            try:
                raise self.retry(exc=exc, countdown=30)
            except MaxRetriesExceededError:
                logger.error(
                    "run_trace: TraceJob %s exhausted all retries — permanently failed",
                    trace_job_id,
                )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_trace_job_model():
    """Lazily import TraceJob to avoid circular imports at module load time."""
    from app.graph.models import TraceJob
    return TraceJob


async def _save_graph_async(
    trace_id: uuid.UUID,
    case_id: uuid.UUID,
    wallet_address: str,
    chain: str,
    G,
) -> None:
    """Persist the graph using a fresh async session.

    Runs inside ``asyncio.run()`` from the synchronous Celery task context.
    A separate :class:`~sqlalchemy.ext.asyncio.AsyncSession` is used so that
    the async persistence layer is independent of the sync Celery session.
    """
    from app.db.session import AsyncSessionLocal
    from app.graph.persistence import save_graph

    async with AsyncSessionLocal() as async_db:
        try:
            await save_graph(
                trace_id=trace_id,
                case_id=case_id,
                wallet_address=wallet_address,
                chain=chain,
                G=G,
                db=async_db,
            )
            await async_db.commit()
        except Exception:
            await async_db.rollback()
            raise
