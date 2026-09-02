"""FastAPI router for SAHYOG Portal submission endpoints.

Exposes:
  POST /reports/{report_id}/submit-sahyog — route a disclosure/freeze request
                                             to the SAHYOG Portal

Requirements: 12.1, 12.3, 12.6, 16.4
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_supervisor
from app.auth.models import User
from app.db.session import get_db
from app.reports.models import Report
from app.sahyog.models import SAHYOGSubmission

router = APIRouter(tags=["sahyog"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class SubmitSAHYOGRequest(BaseModel):
    """Request body for POST /reports/{report_id}/submit-sahyog."""

    request_type: Literal["disclosure", "freeze"] = "disclosure"


class SubmitSAHYOGResponse(BaseModel):
    """Response body after creating a SAHYOG submission."""

    submission_id: uuid.UUID
    case_id: uuid.UUID
    report_id: uuid.UUID
    request_type: str
    status: str
    task_id: str | None = None


# ---------------------------------------------------------------------------
# POST /reports/{report_id}/submit-sahyog
# ---------------------------------------------------------------------------


@router.post(
    "/reports/{report_id}/submit-sahyog",
    response_model=SubmitSAHYOGResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a report to the SAHYOG Portal",
    description=(
        "Creates a SAHYOGSubmission record (status=pending) for the given "
        "report and enqueues a Celery task to deliver it to the SAHYOG Portal. "
        "The submission is processed asynchronously; poll the submission status "
        "to confirm acknowledgement. "
        "Requires the supervisor role. "
        "Requirements: 12.1, 12.3, 12.6, 16.4"
    ),
)
async def submit_to_sahyog(
    report_id: uuid.UUID,
    body: SubmitSAHYOGRequest,
    current_user: Annotated[User, Depends(require_supervisor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """POST /reports/{report_id}/submit-sahyog — enqueue a SAHYOG submission.

    1. Load the Report to verify it exists and is supervisor-approved.
    2. Create a SAHYOGSubmission row with ``status='pending'``.
    3. Flush to get the new submission id, then commit.
    4. Enqueue the ``tasks.sahyog.submit`` Celery task.
    5. Return submission metadata.

    Raises:
        HTTPException(404): If the report does not exist.
        HTTPException(409): If the report has not been supervisor-approved yet.

    Requirements: 12.1, 12.3, 16.4
    """
    # 1. Load and validate the report
    result = await db.execute(select(Report).where(Report.id == report_id))
    report: Report | None = result.scalars().first()

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report {report_id} not found",
        )

    if report.status != "supervisor-approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Report {report_id} must be supervisor-approved before "
                "submitting to SAHYOG. Current status: "
                f"'{report.status}'"
            ),
        )

    # 2. Create SAHYOGSubmission record
    submission = SAHYOGSubmission(
        case_id=report.case_id,
        request_type=body.request_type,
        status="pending",
    )
    db.add(submission)
    await db.flush()  # Populate submission.id before committing

    submission_id_str = str(submission.id)
    case_id = submission.case_id

    await db.commit()

    # 3. Enqueue Celery task (fire-and-forget)
    task_id: str | None = None
    try:
        from app.tasks.sahyog_tasks import submit_sahyog as _celery_task

        async_result = _celery_task.apply_async(
            args=[submission_id_str],
            queue="sahyog",
        )
        task_id = async_result.id
    except Exception:
        # Celery broker unavailable — submission stays in 'pending', will be
        # retried by the operator.  Do not fail the HTTP request.
        import logging
        logging.getLogger(__name__).exception(
            "submit_to_sahyog: failed to enqueue task for submission %s",
            submission_id_str,
        )

    return SubmitSAHYOGResponse(
        submission_id=uuid.UUID(submission_id_str),
        case_id=case_id,
        report_id=report_id,
        request_type=body.request_type,
        status="pending",
        task_id=task_id,
    )
