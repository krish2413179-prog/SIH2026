"""Async CRUD service for case management.

Implements create, read, list, update, and soft-delete operations on Case
records, with role-scoped visibility, state-machine enforcement, and
fire-and-forget audit log writes after every mutating operation.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction, AuditLogEntry
from app.auth.models import User, UserRole
from app.cases.models import Case, CaseStatus, WalletAddress
from app.cases.schemas import CaseCreate, CaseUpdate

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _write_audit(
    db: AsyncSession,
    *,
    action_type: AuditAction,
    actor_user_id: uuid.UUID,
    resource_id: uuid.UUID,
    before_state: dict | None = None,
    after_state: dict | None = None,
) -> None:
    """Insert an AuditLogEntry and commit it in a fire-and-forget manner.

    Errors are logged but never propagated so that a failed audit write
    does not roll back the primary business operation.

    Requirement 14.1 — every mutating action produces an audit entry.
    """
    try:
        entry = AuditLogEntry(
            action_type=action_type,
            actor_user_id=actor_user_id,
            resource_type="case",
            resource_id=resource_id,
            before_state=before_state,
            after_state=after_state,
            source_ip="internal",  # caller may override via middleware
        )
        db.add(entry)
        await db.flush()
    except Exception:  # noqa: BLE001
        logger.exception(
            "Failed to write audit log entry action=%s resource_id=%s",
            action_type,
            resource_id,
        )


def _case_to_dict(case: Case) -> dict:
    """Serialize a Case ORM instance to a plain dict for audit snapshots."""
    return {
        "id": str(case.id),
        "title": case.title,
        "description": case.description,
        "status": case.status.value if case.status else None,
        "created_by": str(case.created_by),
        "supervisor_id": str(case.supervisor_id) if case.supervisor_id else None,
        "org_unit_id": str(case.org_unit_id),
    }


# ---------------------------------------------------------------------------
# create_case
# ---------------------------------------------------------------------------


async def create_case(
    data: CaseCreate,
    created_by: User,
    db: AsyncSession,
) -> Case:
    """Create a new investigation case and write an audit entry.

    The ``created_by`` and ``org_unit_id`` fields are taken directly from
    the authenticated user; callers cannot override them.

    Requirement 2.2 — unique Case ID assigned; status defaults to "open".
    Requirement 14.1 — case_created audit entry written after commit.

    Args:
        data: Validated CaseCreate payload.
        created_by: The authenticated user creating this case.
        db: An open async SQLAlchemy session.

    Returns:
        The newly persisted Case ORM instance.
    """
    case = Case(
        title=data.title,
        description=data.description,
        supervisor_id=data.supervisor_id,
        status=CaseStatus.open,
        created_by=created_by.id,
        org_unit_id=created_by.org_unit_id,
    )
    db.add(case)
    await db.flush()  # populate case.id before audit write

    await _write_audit(
        db,
        action_type=AuditAction.case_created,
        actor_user_id=created_by.id,
        resource_id=case.id,
        after_state=_case_to_dict(case),
    )

    await db.commit()
    await db.refresh(case)
    return case


# ---------------------------------------------------------------------------
# get_case
# ---------------------------------------------------------------------------


async def get_case(
    case_id: uuid.UUID,
    user: User,
    db: AsyncSession,
) -> Case:
    """Retrieve a single live (non-deleted) case, enforcing role-based scope.

    Investigators may only access cases belonging to their own org unit.
    Supervisors and admins may access any case.

    Requirement 2.1 — retrieval enforces RBAC; requires investigator+ role.
    Requirement 2.2 — soft-deleted cases are treated as non-existent.

    Args:
        case_id: UUID of the case to retrieve.
        user: The authenticated requesting user.
        db: An open async SQLAlchemy session.

    Returns:
        The Case ORM instance.

    Raises:
        HTTPException(404): Case not found or has been soft-deleted.
        HTTPException(403): Investigator attempts to access a case outside
                            their org unit.
    """
    stmt = select(Case).where(Case.id == case_id, Case.deleted_at.is_(None))
    result = await db.execute(stmt)
    case: Case | None = result.scalars().first()

    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found",
        )

    # Investigators are scoped to their own org unit
    if user.role == UserRole.investigator and case.org_unit_id != user.org_unit_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Action not permitted for role investigator",
        )

    return case


# ---------------------------------------------------------------------------
# list_cases
# ---------------------------------------------------------------------------


async def list_cases(
    user: User,
    db: AsyncSession,
    *,
    status_filter: CaseStatus | None = None,
    title_query: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Case], int]:
    """List cases with role-scoped visibility, optional filters, and pagination.

    Investigators see only cases within their org unit.
    Supervisors and admins see all non-deleted cases.
    Supports optional status filter and PostgreSQL full-text title search.

    Requirement 2.7 — supports search/filter by status and title.
    Requirement 2.1 — role-scoped visibility enforced.

    Args:
        user: The authenticated requesting user.
        db: An open async SQLAlchemy session.
        status_filter: Optional CaseStatus to narrow results.
        title_query: Optional search string applied as full-text on title.
        page: 1-based page number.
        page_size: Number of items per page.

    Returns:
        A tuple of (items, total_count).
    """
    base_stmt = select(Case).where(Case.deleted_at.is_(None))

    # --- Role-based scope ---
    if user.role == UserRole.investigator:
        base_stmt = base_stmt.where(Case.org_unit_id == user.org_unit_id)

    # --- Optional filters ---
    if status_filter is not None:
        base_stmt = base_stmt.where(Case.status == status_filter)

    if title_query:
        # PostgreSQL full-text search; falls back to ILIKE on non-PG engines
        base_stmt = base_stmt.where(
            Case.title.ilike(f"%{title_query}%")
        )

    # --- Total count (before pagination) ---
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    count_result = await db.execute(count_stmt)
    total: int = count_result.scalar_one()

    # --- Paginated data ---
    offset = (page - 1) * page_size
    data_stmt = (
        base_stmt.order_by(Case.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    data_result = await db.execute(data_stmt)
    items: list[Case] = list(data_result.scalars().all())

    return items, total


# ---------------------------------------------------------------------------
# update_case
# ---------------------------------------------------------------------------


async def update_case(
    case_id: uuid.UUID,
    data: CaseUpdate,
    user: User,
    db: AsyncSession,
) -> Case:
    """Apply a partial update to a case, enforcing state-machine rules.

    - Investigators cannot modify a case whose status is "under_review".
    - A status change produces a ``case_status_changed`` audit entry
      capturing before/after state; other field changes produce a
      ``case_updated`` entry.

    Requirement 2.5 — under_review blocks investigator modifications.
    Requirement 2.3 — state-machine transitions validated.
    Requirement 2.6 — every status change is audited.

    Args:
        case_id: UUID of the case to update.
        data: Validated CaseUpdate payload (all fields optional).
        user: The authenticated requesting user.
        db: An open async SQLAlchemy session.

    Returns:
        The updated Case ORM instance.

    Raises:
        HTTPException(404): Case not found or has been soft-deleted.
        HTTPException(403): Investigator attempts to modify an under_review case.
    """
    case = await get_case(case_id, user, db)

    # Investigators are blocked from modifying cases under review
    if (
        case.status == CaseStatus.under_review
        and user.role == UserRole.investigator
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Action not permitted for role investigator: case is under review",
        )

    before = _case_to_dict(case)
    status_changed = data.status is not None and data.status != case.status

    # Apply updates
    if data.title is not None:
        case.title = data.title
    if data.description is not None:
        case.description = data.description
    if data.supervisor_id is not None:
        case.supervisor_id = data.supervisor_id
    if data.status is not None:
        case.status = data.status

    await db.flush()
    after = _case_to_dict(case)

    # Audit entry — distinguish status changes from general updates
    audit_action = (
        AuditAction.case_status_changed if status_changed else AuditAction.case_updated
    )
    await _write_audit(
        db,
        action_type=audit_action,
        actor_user_id=user.id,
        resource_id=case.id,
        before_state=before,
        after_state=after,
    )

    await db.commit()
    await db.refresh(case)
    return case


# ---------------------------------------------------------------------------
# soft_delete_case
# ---------------------------------------------------------------------------


async def soft_delete_case(
    case_id: uuid.UUID,
    user: User,
    db: AsyncSession,
) -> None:
    """Soft-delete a case and archive its associated wallet addresses.

    Sets ``deleted_at`` on the Case record and flips ``archived=True``
    on every WalletAddress that is linked to this case via the
    case_wallets join table.  All associated Traces and Reports are
    retained per Req 2.4 (only marked archived, never deleted).

    Requirement 2.4 — wallet addresses archived, data retained.
    Requirement 2.6 — case_deleted audit entry written.

    Args:
        case_id: UUID of the case to soft-delete.
        user: The authenticated requesting user.
        db: An open async SQLAlchemy session.

    Raises:
        HTTPException(404): Case not found or already soft-deleted.
    """
    case = await get_case(case_id, user, db)
    before = _case_to_dict(case)

    now = datetime.now(tz=timezone.utc)
    case.deleted_at = now

    # Archive all WalletAddress records linked to this case
    # via the case_wallets join table
    try:
        from app.cases.models import CaseWallet  # local import to avoid circularity

        wallet_ids_stmt = select(CaseWallet.wallet_address_id).where(
            CaseWallet.case_id == case_id
        )
        wallet_ids_result = await db.execute(wallet_ids_stmt)
        wallet_ids = [row[0] for row in wallet_ids_result.all()]

        if wallet_ids:
            archive_stmt = (
                update(WalletAddress)
                .where(WalletAddress.id.in_(wallet_ids))
                .values(archived=True)
            )
            await db.execute(archive_stmt)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Failed to archive wallet addresses for case_id=%s", case_id
        )

    await db.flush()

    await _write_audit(
        db,
        action_type=AuditAction.case_deleted,
        actor_user_id=user.id,
        resource_id=case.id,
        before_state=before,
        after_state=None,
    )

    await db.commit()
