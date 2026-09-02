"""Pydantic v2 schemas for the VASP registry.

Covers request/response shapes for VASP CRUD and address management.

Requirements: 7.1, 7.2, 7.3
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.vasp_db.models import VASPCategory


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class VASPCreate(BaseModel):
    """Payload for POST /admin/vasps — register a new VASP.

    Requirement 7.2 — admin can create VASP records with full metadata.
    """

    name: str = Field(..., min_length=1, max_length=255, description="Full legal / commonly-known name of the VASP")
    category: VASPCategory = Field(..., description="CEX | DEX | mixer | bridge | darknet | other")
    jurisdiction: str = Field(
        ...,
        min_length=2,
        max_length=2,
        description="ISO 3166-1 alpha-2 country code",
    )
    operational_status: str = Field(
        ...,
        description="active | inactive | sanctioned",
    )


class VASPUpdate(BaseModel):
    """Payload for PATCH /admin/vasps/{vasp_id} — partial update of a VASP.

    All fields are optional so callers may update only what has changed.
    After a successful update the service marks affected trace_jobs with
    needs_reattribution=True and publishes a pg_notify event.

    Requirement 7.2 — admin can update VASP records.
    """

    name: str | None = Field(None, min_length=1, max_length=255)
    category: VASPCategory | None = None
    jurisdiction: str | None = Field(None, min_length=2, max_length=2)
    operational_status: str | None = None


class VASPAddressCreate(BaseModel):
    """Payload for adding an on-chain address to a VASP.

    Requirement 7.1 — VASP addresses are tracked per chain.
    """

    chain: str = Field(
        ...,
        description="Blockchain identifier: BTC | ETH | TRX | BSC | SOL | MATIC",
    )
    address: str = Field(..., description="On-chain address string (raw, not normalised)")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class VASPResponse(BaseModel):
    """Full VASP representation returned to API consumers.

    Requirement 7.3 — includes all required VASP fields.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    category: VASPCategory
    jurisdiction: str
    operational_status: str
    last_updated: datetime


class VASPListResponse(BaseModel):
    """Paginated list of VASPs.

    Requirement 7.3 — paginated VASP listing with total count.
    """

    items: list[VASPResponse]
    total: int
