"""FastAPI router for investigation report endpoints.

Exposes:
  POST /traces/{trace_id}/reports   — generate a report for a completed trace
  GET  /reports/{report_id}         — retrieve a report by ID
  POST /reports/{report_id}/sign    — supervisor approval / signing

Requirements: 11.1, 11.2, 11.3, 11.5, 11.6, 11.7
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_investigator, require_supervisor
from app.auth.models import User
from app.db.session import get_db
from app.reports import service
from app.reports.models import Report

router = APIRouter(tags=["reports"])


# ---------------------------------------------------------------------------
# GET /reports — list reports, optionally filtered by case_id
# ---------------------------------------------------------------------------


@router.get(
    "/reports",
    summary="List reports",
)
async def list_reports(
    current_user: Annotated[User, Depends(require_investigator)],
    db: Annotated[AsyncSession, Depends(get_db)],
    case_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """GET /reports — list all reports, optionally filtered by case_id."""
    stmt = select(Report)
    if case_id is not None:
        stmt = stmt.where(Report.case_id == case_id)
    stmt = stmt.order_by(Report.created_at.desc())
    result = await db.execute(stmt)
    reports = result.scalars().all()
    return [_report_response(r) for r in reports]


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class GenerateReportRequest(BaseModel):
    """Request body for POST /traces/{trace_id}/reports."""

    format: Literal["pdf", "json"] = "json"


def _report_response(report: Report) -> dict[str, Any]:
    """Serialise a Report ORM instance to a response dict."""
    return {
        "report_id": report.id,
        "case_id": report.case_id,
        "trace_id": report.trace_id,
        "generated_by": report.generated_by,
        "format": report.format,
        "status": report.status,
        "content_hash": report.content_hash,
        "supervisor_signature": report.supervisor_signature,
        "created_at": report.created_at,
        # Include JSON payload inline for JSON-format reports
        "json_payload": report.json_payload if report.format == "json" else None,
        # S3 key for PDF reports (consumers can use this to fetch the PDF)
        "s3_key": report.s3_key if report.format == "pdf" else None,
    }


# ---------------------------------------------------------------------------
# POST /traces/{trace_id}/reports
# ---------------------------------------------------------------------------


@router.post(
    "/traces/{trace_id}/reports",
    status_code=status.HTTP_201_CREATED,
    summary="Generate an investigation report for a trace",
    description=(
        "Generates a new investigation report (PDF or JSON) from the completed "
        "trace identified by *trace_id*. The report is persisted in the database "
        "and returned as report metadata. "
        "Requires at minimum the investigator role. "
        "Requirements: 11.1, 11.2, 11.3, 11.5, 11.6"
    ),
)
async def generate_report(
    trace_id: uuid.UUID,
    body: GenerateReportRequest,
    current_user: Annotated[User, Depends(require_investigator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """POST /traces/{trace_id}/reports — generate and persist an investigation report.

    Calls the report generation service which:
    - Loads the TraceJob and parent Case (404 on missing).
    - Collects VASP attributions, typology tags, wallet addresses, and
      the transaction graph timeline.
    - Renders the report to bytes (PDF via WeasyPrint or JSON via Pydantic).
    - Computes a SHA-256 content hash over the rendered payload.
    - Persists the Report ORM row with status "draft".
    - Writes a ``report_generated`` audit log entry.

    Returns the persisted report metadata.

    Raises:
        HTTPException(404): TraceJob or Case not found.

    Requirements: 11.1, 11.2, 11.3, 11.5, 11.6
    """
    report = await service.generate_report(
        trace_id=trace_id,
        format=body.format,
        generated_by_user=current_user,
        db=db,
    )
    return _report_response(report)


# ---------------------------------------------------------------------------
# GET /reports/{report_id}
# ---------------------------------------------------------------------------


@router.get(
    "/reports/{report_id}",
    summary="Retrieve a report by ID",
    description=(
        "Returns the full report metadata (and JSON payload for JSON-format reports) "
        "for the report identified by *report_id*. "
        "Requires at minimum the investigator role. "
        "Requirements: 11.1, 11.5, 11.6"
    ),
)
async def get_report(
    report_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_investigator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """GET /reports/{report_id} — return a report record by its primary key.

    Returns the persisted report metadata. For JSON-format reports the full
    ``json_payload`` is included; for PDF reports the ``s3_key`` is returned
    so callers can retrieve the file from object storage.

    Raises:
        HTTPException(404): If no Report exists with the given *report_id*.

    Requirements: 11.1, 11.5, 11.6
    """
    result = await db.execute(select(Report).where(Report.id == report_id))
    report: Report | None = result.scalars().first()

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report {report_id} not found",
        )

    return _report_response(report)


# ---------------------------------------------------------------------------
# POST /reports/{report_id}/sign
# ---------------------------------------------------------------------------


@router.post(
    "/reports/{report_id}/sign",
    summary="Supervisor approval: sign a report",
    description=(
        "Signs the report identified by *report_id*, setting "
        "``supervisor_signature = '{supervisor_id}:{iso_timestamp}:{content_hash}'`` "
        "and updating ``status`` to ``supervisor-approved``. "
        "Requires the supervisor role. "
        "Requirements: 11.6, 11.7"
    ),
)
async def sign_report(
    report_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_supervisor)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """POST /reports/{report_id}/sign — supervisor-sign a draft report.

    Applies a supervisor signature of the form::

        {supervisor_user_id}:{iso_utc_timestamp}:{content_hash}

    and transitions the report status from ``draft`` to
    ``supervisor-approved``. Writes a ``report_signed`` audit log entry.

    Raises:
        HTTPException(404): If no Report exists with the given *report_id*.

    Requirements: 11.6, 11.7
    """
    report = await service.sign_report(
        report_id=report_id,
        supervisor=current_user,
        db=db,
    )
    return _report_response(report)
