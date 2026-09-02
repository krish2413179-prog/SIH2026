"""SAHYOG service layer — config loading and submission orchestration.

Loads SAHYOG configuration from environment/settings, constructs the
SAHYOGClient, submits payloads, and updates submission status in the DB.

Requirements: 12.1, 12.3, 16.4
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.sahyog.client import SAHYOGClient, SAHYOGConfig, SAHYOGSubmissionPayload
from app.sahyog.models import SAHYOGSubmission

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


async def get_config(db: AsyncSession) -> SAHYOGConfig | None:  # noqa: ARG001
    """Load SAHYOG Portal configuration from application settings.

    MVP implementation: reads from environment variables / application
    config (``app.config.Settings``).  A future enhancement could store
    per-org-unit configs in a settings table and read them here.

    Returns ``None`` when ``sahyog_endpoint_url`` is not configured (i.e.,
    the integration is disabled for this deployment).

    Args:
        db: Async database session (reserved for future DB-backed config).

    Requirements: 12.1
    """
    from app.config import get_settings

    settings = get_settings()

    if not settings.sahyog_endpoint_url:
        return None

    return SAHYOGConfig(
        endpoint_url=settings.sahyog_endpoint_url,
        auth_type=settings.sahyog_auth_type,
        api_key=settings.sahyog_api_key or None,
    )


# ---------------------------------------------------------------------------
# Submission orchestration
# ---------------------------------------------------------------------------


async def submit_to_sahyog(
    submission_id: str | uuid.UUID,
    db: AsyncSession,
    redis_client: "aioredis.Redis | None" = None,  # reserved for future caching
) -> dict:
    """Load a SAHYOGSubmission, call SAHYOGClient.submit(), and update status.

    Steps:
    1. Load the ``SAHYOGSubmission`` row by *submission_id*.
    2. Load the parent ``Case`` to get the case title.
    3. Load the parent ``Report`` to get the content hash and wallet addresses.
    4. Build a :class:`~app.sahyog.client.SAHYOGSubmissionPayload`.
    5. Submit via :class:`~app.sahyog.client.SAHYOGClient`.
    6. On success: update submission ``status`` and ``portal_reference_number``.
    7. On failure: update ``status = "failed"`` and re-raise.

    Args:
        submission_id: UUID of the ``SAHYOGSubmission`` row to process.
        db: Async database session.
        redis_client: Optional Redis client (reserved for future caching).

    Returns:
        Dict containing ``submission_id``, ``status``, and
        ``portal_reference_number``.

    Raises:
        ValueError: If the submission, config, or related records are not found.
        httpx.HTTPError: On portal communication failures.

    Requirements: 12.1, 12.3, 16.4
    """
    from app.cases.models import Case, CaseWallet, WalletAddress
    from app.reports.models import Report

    sub_uuid = uuid.UUID(str(submission_id))

    # 1. Load submission
    result = await db.execute(
        select(SAHYOGSubmission).where(SAHYOGSubmission.id == sub_uuid)
    )
    submission: SAHYOGSubmission | None = result.scalars().first()
    if submission is None:
        raise ValueError(f"SAHYOGSubmission {submission_id} not found")

    # 2. Load parent case
    case_result = await db.execute(
        select(Case).where(Case.id == submission.case_id)
    )
    case: Case | None = case_result.scalars().first()
    if case is None:
        raise ValueError(f"Case {submission.case_id} not found")

    # 3. Load the most recent approved report for this case to get the hash
    #    The submission was created from a specific report; look it up via
    #    the report_id stored in the submission's extra metadata if available,
    #    otherwise use the latest approved report.
    report_result = await db.execute(
        select(Report)
        .where(Report.case_id == submission.case_id)
        .order_by(Report.created_at.desc())
        .limit(1)
    )
    report: Report | None = report_result.scalars().first()
    if report is None:
        raise ValueError(f"No report found for case {submission.case_id}")

    # 4. Collect wallet addresses for this case
    wallets_result = await db.execute(
        select(WalletAddress)
        .join(CaseWallet, CaseWallet.wallet_address_id == WalletAddress.id)
        .where(CaseWallet.case_id == submission.case_id)
    )
    wallet_addresses = [w.address_plain for w in wallets_result.scalars().all()]

    # 5. Load SAHYOG config
    config = await get_config(db)
    if config is None:
        submission.status = "failed"
        await db.commit()
        raise ValueError("SAHYOG Portal is not configured (sahyog_endpoint_url is empty)")

    # 6. Build payload
    evidence_summary = (
        f"Investigation case '{case.title}'. "
        f"Wallet addresses under review: {len(wallet_addresses)}. "
        f"Report hash: {report.content_hash}."
    )

    payload = SAHYOGSubmissionPayload(
        request_type=submission.request_type,  # type: ignore[arg-type]
        case_id=str(submission.case_id),
        case_title=case.title,
        wallet_addresses=wallet_addresses,
        report_id=str(report.id),
        report_hash=report.content_hash,
        evidence_summary=evidence_summary,
        submitted_by=str(submission.case_id),  # submission owner tracked via case
    )

    # 7. Submit via client and update DB
    client = SAHYOGClient(config=config)
    try:
        portal_response = await client.submit(payload)

        submission.status = portal_response.status  # acknowledged | rejected
        submission.portal_reference_number = portal_response.reference_number
        await db.commit()

        logger.info(
            "SAHYOG submission %s completed with status=%s reference=%s",
            submission_id,
            portal_response.status,
            portal_response.reference_number,
        )

        return {
            "submission_id": str(submission.id),
            "status": submission.status,
            "portal_reference_number": submission.portal_reference_number,
            "message": portal_response.message,
        }

    except Exception as exc:
        logger.exception("SAHYOG submission %s failed: %s", submission_id, exc)
        submission.status = "failed"
        await db.commit()
        raise
