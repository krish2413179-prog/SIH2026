"""FastAPI router for audit log export.

Exposes:
  GET /admin/audit-logs/export — export audit log entries as CSV or JSON

Requirements: 14.4, 15.4, 15.5
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction, AuditLogEntry
from app.auth.dependencies import require_admin
from app.auth.models import User
from app.db.session import get_db

router = APIRouter(prefix="/admin/audit-logs", tags=["admin", "audit"])


# ---------------------------------------------------------------------------
# GET /admin/audit-logs/export
# ---------------------------------------------------------------------------


@router.get(
    "/export",
    summary="Export audit log entries",
    description=(
        "Export audit log entries filtered by date range, actor, action type, "
        "and/or resource. Returns CSV or JSON inline (up to 10,000 rows). "
        "Requires the admin role. "
        "Requirements: 14.4, 15.4, 15.5"
    ),
    status_code=status.HTTP_200_OK,
)
async def export_audit_logs(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    from_date: Annotated[
        datetime | None,
        Query(description="Filter entries on or after this UTC datetime (ISO 8601)"),
    ] = None,
    to_date: Annotated[
        datetime | None,
        Query(description="Filter entries on or before this UTC datetime (ISO 8601)"),
    ] = None,
    user_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by actor user UUID"),
    ] = None,
    action_type: Annotated[
        AuditAction | None,
        Query(description="Filter by action type"),
    ] = None,
    resource_id: Annotated[
        uuid.UUID | None,
        Query(description="Filter by affected resource UUID"),
    ] = None,
    format: Annotated[
        str,
        Query(description="Output format: csv or json", pattern="^(csv|json)$"),
    ] = "json",
) -> Response:
    """GET /admin/audit-logs/export — export filtered audit log entries.

    Applies optional filters on ``timestamp``, ``actor_user_id``,
    ``action_type``, and ``resource_id``.  Returns up to 10,000 rows
    inline as CSV or JSON.

    CSV columns (in order):
      id, timestamp, actor_user_id, action_type, resource_type,
      resource_id, source_ip, session_id

    Requirements: 14.4, 15.4, 15.5
    """
    _MAX_ROWS = 10_000

    # Build query with optional filters
    query = select(AuditLogEntry).order_by(AuditLogEntry.timestamp.desc())

    if from_date is not None:
        # Ensure timezone-aware comparison
        if from_date.tzinfo is None:
            from_date = from_date.replace(tzinfo=timezone.utc)
        query = query.where(AuditLogEntry.timestamp >= from_date)

    if to_date is not None:
        if to_date.tzinfo is None:
            to_date = to_date.replace(tzinfo=timezone.utc)
        query = query.where(AuditLogEntry.timestamp <= to_date)

    if user_id is not None:
        query = query.where(AuditLogEntry.actor_user_id == user_id)

    if action_type is not None:
        query = query.where(AuditLogEntry.action_type == action_type)

    if resource_id is not None:
        query = query.where(AuditLogEntry.resource_id == resource_id)

    # Limit to prevent accidental full-table dumps in a single request
    query = query.limit(_MAX_ROWS)

    result = await db.execute(query)
    entries: list[AuditLogEntry] = list(result.scalars().all())

    if format == "csv":
        return _build_csv_response(entries)
    else:
        return _build_json_response(entries)


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def _entry_to_dict(entry: AuditLogEntry) -> dict:
    """Serialise an AuditLogEntry to a plain dictionary."""
    return {
        "id": str(entry.id),
        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
        "actor_user_id": str(entry.actor_user_id) if entry.actor_user_id else None,
        "action_type": entry.action_type.value if entry.action_type else None,
        "resource_type": entry.resource_type,
        "resource_id": str(entry.resource_id) if entry.resource_id else None,
        "source_ip": entry.source_ip,
        "session_id": entry.session_id,
        "before_state": entry.before_state,
        "after_state": entry.after_state,
    }


def _build_json_response(entries: list[AuditLogEntry]) -> Response:
    """Serialise entries to a JSON response."""
    data = [_entry_to_dict(e) for e in entries]
    body = json.dumps({"count": len(data), "entries": data}, default=str)
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="audit_logs.json"',
            "X-Total-Count": str(len(data)),
        },
    )


def _build_csv_response(entries: list[AuditLogEntry]) -> Response:
    """Serialise entries to a CSV response."""
    output = io.StringIO()
    fieldnames = [
        "id",
        "timestamp",
        "actor_user_id",
        "action_type",
        "resource_type",
        "resource_id",
        "source_ip",
        "session_id",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()

    for entry in entries:
        row = _entry_to_dict(entry)
        # CSV rows don't include before_state/after_state (JSONB columns — keep out of flat CSV)
        writer.writerow({k: row[k] for k in fieldnames})

    csv_content = output.getvalue()
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="audit_logs.csv"',
            "X-Total-Count": str(len(entries)),
        },
    )
