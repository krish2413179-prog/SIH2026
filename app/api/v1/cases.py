"""FastAPI router for case management endpoints.

Exposes CRUD operations on investigation cases with JWT+RBAC protection.
All endpoints require at least the investigator role (investigator, supervisor, admin).

Requirements: 2.1, 2.5, 2.7
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_investigator
from app.auth.models import User
from app.cases import service
from app.cases.models import CaseStatus
from app.cases.schemas import CaseCreate, CaseListResponse, CaseResponse, CaseUpdate
from app.db.session import get_db

router = APIRouter(prefix="/cases", tags=["cases"])


# ---------------------------------------------------------------------------
# POST /cases — create a new investigation case
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=CaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new investigation case",
    description=(
        "Create a new case. The case is assigned status 'open' automatically. "
        "The authenticated user becomes the case owner; org_unit_id is derived "
        "from their account. Requirement 2.1, 2.2."
    ),
)
async def create_case(
    data: CaseCreate,
    current_user: Annotated[User, Depends(require_investigator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CaseResponse:
    case = await service.create_case(data=data, created_by=current_user, db=db)
    return CaseResponse.model_validate(case)


# ---------------------------------------------------------------------------
# GET /cases — list / search cases (role-filtered, paginated)
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=CaseListResponse,
    summary="List and search investigation cases",
    description=(
        "Return a paginated list of cases visible to the current user. "
        "Investigators see only cases within their org unit; supervisors and admins "
        "see all cases. Supports optional status filter and title substring search. "
        "Requirement 2.7."
    ),
)
async def list_cases(
    current_user: Annotated[User, Depends(require_investigator)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status: CaseStatus | None = Query(None, description="Filter by case status"),
    q: str | None = Query(None, description="Title substring search string"),
    page: int = Query(1, ge=1, description="1-based page number"),
    page_size: int = Query(20, ge=1, le=100, description="Number of items per page (max 100)"),
) -> CaseListResponse:
    items, total = await service.list_cases(
        user=current_user,
        db=db,
        status_filter=status,
        title_query=q,
        page=page,
        page_size=page_size,
    )
    return CaseListResponse(
        items=[CaseResponse.model_validate(c) for c in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# GET /cases/{case_id} — retrieve a single case
# ---------------------------------------------------------------------------


@router.get(
    "/{case_id}",
    response_model=CaseResponse,
    summary="Get case details",
    description=(
        "Retrieve a single live (non-deleted) case by ID. "
        "Investigators may only access cases within their own org unit. "
        "Returns 404 if not found or soft-deleted."
    ),
)
async def get_case(
    case_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_investigator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CaseResponse:
    # service.get_case raises 404 or 403 as appropriate
    case = await service.get_case(case_id=case_id, user=current_user, db=db)
    return CaseResponse.model_validate(case)


# ---------------------------------------------------------------------------
# PATCH /cases/{case_id} — partial update
# ---------------------------------------------------------------------------


@router.patch(
    "/{case_id}",
    response_model=CaseResponse,
    summary="Update a case",
    description=(
        "Apply a partial update to a case. All fields are optional. "
        "Investigators are blocked from modifying cases whose status is 'under_review' (403). "
        "Status transitions follow the open → under_review → closed state machine. "
        "Every status change is recorded in the Audit Log. "
        "Requirements 2.3, 2.5, 2.6."
    ),
)
async def update_case(
    case_id: uuid.UUID,
    data: CaseUpdate,
    current_user: Annotated[User, Depends(require_investigator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CaseResponse:
    # service.update_case raises 404 if not found, 403 if under-review block applies
    case = await service.update_case(
        case_id=case_id,
        data=data,
        user=current_user,
        db=db,
    )
    return CaseResponse.model_validate(case)


# ---------------------------------------------------------------------------
# DELETE /cases/{case_id} — soft-delete
# ---------------------------------------------------------------------------


@router.delete(
    "/{case_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a case",
    description=(
        "Soft-delete a case by setting deleted_at. Associated wallet addresses are "
        "archived. Case data is retained for audit purposes. Returns 204 on success. "
        "Requirement 2.4, 2.6."
    ),
)
async def delete_case(
    case_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_investigator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    # service.soft_delete_case raises 404 if not found
    await service.soft_delete_case(case_id=case_id, user=current_user, db=db)
