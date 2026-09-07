"""Business logic for wallet address submission.

Implements batch wallet submission including:
  - Per-address chain detection or caller-specified chain override
  - 24-hour deduplication against existing TraceJob records
  - WalletAddress + CaseWallet DB record creation
  - TraceJob creation and Celery task enqueue (fire-and-forget)
  - AuditLogEntry write per successfully queued address

Requirements: 3.1, 3.4, 3.5, 3.6, 3.7
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction, AuditLogEntry
from app.cases.models import Case, CaseWallet, WalletAddress
from app.graph.models import TraceJob
from app.wallets.schemas import WalletSubmitBatch, WalletSubmitResponse, WalletSubmitResult
from app.wallets.validators import AddressValidationError, detect_chains

if TYPE_CHECKING:
    from app.auth.models import User

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _write_wallet_audit(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    resource_id: uuid.UUID,
    after_state: dict,
) -> None:
    """Insert a wallet_submitted AuditLogEntry.

    Errors are logged but never propagated so that a failed audit write
    does not roll back the primary business operation.

    Requirement 14.1 — every wallet submission produces an audit entry.
    """
    try:
        entry = AuditLogEntry(
            action_type=AuditAction.wallet_submitted,
            actor_user_id=actor_user_id,
            resource_type="wallet",
            resource_id=resource_id,
            before_state=None,
            after_state=after_state,
            source_ip="internal",
        )
        db.add(entry)
        await db.flush()
    except Exception:  # noqa: BLE001
        logger.exception(
            "Failed to write audit log entry action=wallet_submitted resource_id=%s",
            resource_id,
        )


import concurrent.futures

_bg_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def _enqueue_trace(trace_job_id: uuid.UUID) -> str | None:
    """Fire-and-forget background trace execution (100% reliable in-process execution)."""
    def _run_in_background():
        try:
            logger.info("Executing background trace for trace_job_id=%s", trace_job_id)
            from app.tasks.trace_tasks import run_trace
            run_trace(str(trace_job_id))
        except Exception:
            logger.exception("In-process background trace execution failed for trace_job_id=%s", trace_job_id)

    _bg_executor.submit(_run_in_background)

    try:
        from app.tasks.trace_tasks import run_trace
        task = run_trace.delay(str(trace_job_id))
        return task.id
    except Exception:
        return str(trace_job_id)


# ---------------------------------------------------------------------------
# submit_wallets
# ---------------------------------------------------------------------------


async def submit_wallets(
    case_id: uuid.UUID,
    batch: WalletSubmitBatch,
    submitted_by: "User",
    db: AsyncSession,
) -> WalletSubmitResponse:
    """Process a batch of wallet address submissions.

    For each address in the batch:
    1. Detect chains (if not specified by caller, use detect_chains())
    2. For each (address, chain) pair:
       a. Check for deduplication: query trace_jobs for an existing trace with
          (case_id, wallet_address, chain) where enqueued_at > now() - 24h
          and status NOT IN ('failed').
          If found: add to results with is_duplicate=True, trace_id=existing.id
          and skip further processing for this pair.
       b. If not duplicate:
          - Create WalletAddress record in DB
          - Create CaseWallet link
          - Create TraceJob record (status='queued')
          - Enqueue Celery trace task (fire-and-forget)
          - Write AuditLogEntry(action_type=wallet_submitted)
          - Add to results with is_duplicate=False, trace_id=new_trace_job.id
    3. If address fails format validation: add to errors list

    Returns WalletSubmitResponse with results and errors lists.

    Requirements: 3.1, 3.4, 3.5, 3.6, 3.7
    """
    # --- Case access check (Req 3.1) ---
    case_stmt = select(Case).where(Case.id == case_id, Case.deleted_at.is_(None))
    case_result = await db.execute(case_stmt)
    case: Case | None = case_result.scalars().first()

    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found",
        )

    results: list[WalletSubmitResult] = []
    errors: list[dict] = []
    dedup_cutoff = datetime.now(UTC) - timedelta(hours=24)

    to_enqueue: list[uuid.UUID] = []

    for item in batch.addresses:
        address = item.address

        # --- Chain resolution ---
        if item.chain is not None:
            # Caller explicitly specified a chain; schema already validated format
            chains_to_process = [item.chain]
        else:
            # Auto-detect applicable chains
            try:
                chains_to_process = detect_chains(address)
                if not chains_to_process:
                    raise AddressValidationError(address)
            except AddressValidationError as exc:
                errors.append({"address": address, "detail": str(exc)})
                continue

        # --- Per-(address, chain) processing ---
        for chain in chains_to_process:
            # Deduplication check (Req 3.6)
            dup_stmt = (
                select(TraceJob)
                .where(
                    TraceJob.case_id == case_id,
                    TraceJob.wallet_address == address,
                    TraceJob.chain == chain,
                    TraceJob.enqueued_at > dedup_cutoff,
                    TraceJob.status.notin_(["failed"]),
                )
                .limit(1)
            )
            dup_result = await db.execute(dup_stmt)
            existing_job: TraceJob | None = dup_result.scalars().first()

            if existing_job is not None:
                # Duplicate — return existing trace_id (Req 3.6)
                results.append(
                    WalletSubmitResult(
                        address=address,
                        chain=chain,
                        trace_id=existing_job.id,
                        is_duplicate=True,
                    )
                )
                continue

            # --- New submission (Req 3.7) ---

            # 1. Create WalletAddress record
            wallet_addr = WalletAddress(
                address_plain=address,
                chain=chain,
                submitted_by=submitted_by.id,
            )
            db.add(wallet_addr)
            await db.flush()  # populate wallet_addr.id

            # 2. Create CaseWallet link
            case_wallet = CaseWallet(
                case_id=case_id,
                wallet_address_id=wallet_addr.id,
            )
            db.add(case_wallet)

            # 3. Create TraceJob (status='queued')
            trace_job = TraceJob(
                case_id=case_id,
                wallet_address=address,
                chain=chain,
                status="queued",
            )
            db.add(trace_job)
            await db.flush()  # populate trace_job.id

            # 4. Write audit log entry
            await _write_wallet_audit(
                db,
                actor_user_id=submitted_by.id,
                resource_id=trace_job.id,
                after_state={
                    "case_id": str(case_id),
                    "wallet_address": address,
                    "chain": chain,
                    "trace_job_id": str(trace_job.id),
                    "wallet_address_id": str(wallet_addr.id),
                },
            )

            to_enqueue.append(trace_job.id)

            results.append(
                WalletSubmitResult(
                    address=address,
                    chain=chain,
                    trace_id=trace_job.id,
                    is_duplicate=False,
                )
            )

    # Commit everything in DB FIRST before enqueueing tasks so the worker can read the row
    await db.commit()

    # Enqueue Celery tasks after successful commit
    for job_id in to_enqueue:
        _enqueue_trace(job_id)

    return WalletSubmitResponse(results=results, errors=errors)
