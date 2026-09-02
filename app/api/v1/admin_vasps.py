"""Admin CRUD endpoints for the VASP registry.

All routes require admin-level authentication.

Requirements: 7.1, 7.2, 7.3
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.auth.models import User
from app.db.session import get_db
from app.vasp_db import service
from app.vasp_db.schemas import (
    VASPCreate,
    VASPListResponse,
    VASPResponse,
    VASPUpdate,
)

router = APIRouter(prefix="/admin/vasps", tags=["admin", "vasps"])


# NOTE: /search must be declared BEFORE /{vasp_id} to avoid path conflicts.
@router.get("/search", response_model=list[VASPResponse])
async def search_vasps(
    q: Annotated[str, Query(description="Search term matched against VASP name (ILIKE) or exact on-chain address")],
    chain: Annotated[str | None, Query(description="Restrict address search to this blockchain")] = None,
    _current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[VASPResponse]:
    """Search VASPs by name or on-chain address.

    Requirement 7.3 — VASP search by name or address.
    """
    vasps = await service.search_vasps(query=q, chain=chain, db=db)
    return [VASPResponse.model_validate(v) for v in vasps]


@router.get("", response_model=VASPListResponse)
async def list_vasps(
    page: Annotated[int, Query(ge=1, description="1-based page number")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Items per page (max 100)")] = 20,
    _current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> VASPListResponse:
    """List all VASPs with pagination.

    Requirement 7.3 — paginated VASP listing.
    """
    items, total = await service.list_vasps(db, page=page, page_size=page_size)
    return VASPListResponse(
        items=[VASPResponse.model_validate(v) for v in items],
        total=total,
    )


@router.post("", response_model=VASPResponse, status_code=status.HTTP_201_CREATED)
async def create_vasp(
    payload: VASPCreate,
    _current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> VASPResponse:
    """Register a new VASP.

    Requirement 7.2 — admin can create VASP records.
    """
    vasp = await service.create_vasp(data=payload, db=db)
    return VASPResponse.model_validate(vasp)


@router.get("/{vasp_id}", response_model=VASPResponse)
async def get_vasp(
    vasp_id: uuid.UUID,
    _current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> VASPResponse:
    """Retrieve a single VASP by ID.

    Requirement 7.3 — returns full VASP details.
    """
    vasp = await service.get_vasp(vasp_id=vasp_id, db=db)
    return VASPResponse.model_validate(vasp)


@router.patch("/{vasp_id}", response_model=VASPResponse)
async def update_vasp(
    vasp_id: uuid.UUID,
    payload: VASPUpdate,
    _current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> VASPResponse:
    """Partially update a VASP record.

    Triggers reattribution on affected trace jobs and publishes a pg_notify event.

    Requirement 7.2 — admin can update VASP records.
    """
    vasp = await service.update_vasp(vasp_id=vasp_id, data=payload, db=db)
    return VASPResponse.model_validate(vasp)


@router.delete("/{vasp_id}", response_model=VASPResponse)
async def deactivate_vasp(
    vasp_id: uuid.UUID,
    _current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> VASPResponse:
    """Soft-deactivate a VASP (sets operational_status to 'inactive').

    Requirement 7.2 — admin can deactivate VASP records.
    """
    vasp = await service.deactivate_vasp(vasp_id=vasp_id, db=db)
    return VASPResponse.model_validate(vasp)
