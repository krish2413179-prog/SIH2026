"""Pydantic v2 schemas for case management.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.cases.models import CaseStatus


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CaseCreate(BaseModel):
    """Payload for POST /cases — create a new investigation case.

    Requirement 2.2 — The Engine SHALL assign status "open" on creation;
    the caller provides title, optional description, and optional supervisor.
    """

    title: str = Field(..., min_length=1, max_length=255, description="Short case title")
    description: str | None = Field(None, description="Optional detailed description")
    supervisor_id: uuid.UUID | None = Field(None, description="UUID of an assigned supervisor")


class CaseUpdate(BaseModel):
    """Payload for PATCH /cases/{id} — partial update of a case.

    All fields are optional so callers may update only what has changed.
    Requirement 2.3 — status field participates in the open → under_review → closed
    state machine; the service layer enforces valid transitions.
    Requirement 2.5 — investigators are blocked from modifying under_review cases.
    """

    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    supervisor_id: uuid.UUID | None = None
    status: CaseStatus | None = None


class CaseStatusTransition(BaseModel):
    """Payload for an explicit status-change endpoint.

    Used when a dedicated PATCH /cases/{id}/status endpoint is provided
    to make status transitions unambiguous and separately auditable.
    Requirement 2.6 — every status change is recorded in the Audit Log.
    """

    new_status: CaseStatus = Field(..., description="Target lifecycle state")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class CaseResponse(BaseModel):
    """Full case representation returned to API consumers.

    Requirement 2.3 — includes all required Case fields.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    title: str
    description: str | None
    status: CaseStatus
    created_by: uuid.UUID
    supervisor_id: uuid.UUID | None
    org_unit_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class CaseListResponse(BaseModel):
    """Paginated list of cases.

    Requirement 2.7 — supports search and filter; pagination metadata included.
    """

    items: list[CaseResponse]
    total: int
    page: int
    page_size: int
