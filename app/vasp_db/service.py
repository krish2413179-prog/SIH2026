"""Async CRUD service for the VASP registry.

Implements create, read, list, update, deactivate, and search operations on
VASP records. On VASP updates, marks affected trace_jobs with
needs_reattribution=True and publishes a pg_notify event (fire-and-forget).

Requirements: 7.1, 7.2, 7.3
"""

from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.vasp_db.models import VASP, VASPAddress
from app.vasp_db.schemas import VASPCreate, VASPUpdate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# create_vasp
# ---------------------------------------------------------------------------


async def create_vasp(data: VASPCreate, db: AsyncSession) -> VASP:
    """Create a new VASP registry entry.

    Requirement 7.2 — admin can create VASP records.

    Args:
        data: Validated VASPCreate payload.
        db: An open async SQLAlchemy session.

    Returns:
        The newly persisted VASP ORM instance.
    """
    vasp = VASP(
        name=data.name,
        category=data.category,
        jurisdiction=data.jurisdiction,
        operational_status=data.operational_status,
    )
    db.add(vasp)
    await db.flush()
    await db.refresh(vasp)
    return vasp


# ---------------------------------------------------------------------------
# get_vasp
# ---------------------------------------------------------------------------


async def get_vasp(vasp_id: uuid.UUID, db: AsyncSession) -> VASP:
    """Retrieve a single VASP by ID.

    Requirement 7.3 — returns full VASP details.

    Args:
        vasp_id: UUID of the VASP to retrieve.
        db: An open async SQLAlchemy session.

    Returns:
        The VASP ORM instance.

    Raises:
        HTTPException(404): VASP not found.
    """
    result = await db.execute(select(VASP).where(VASP.id == vasp_id))
    vasp: VASP | None = result.scalars().first()

    if vasp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="VASP not found",
        )

    return vasp


# ---------------------------------------------------------------------------
# list_vasps
# ---------------------------------------------------------------------------


async def list_vasps(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[VASP], int]:
    """List all VASPs with pagination.

    Requirement 7.3 — paginated VASP listing.

    Args:
        db: An open async SQLAlchemy session.
        page: 1-based page number.
        page_size: Number of items per page.

    Returns:
        A tuple of (items, total_count).
    """
    base_stmt = select(VASP)

    # Total count
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    count_result = await db.execute(count_stmt)
    total: int = count_result.scalar_one()

    # Paginated data
    offset = (page - 1) * page_size
    data_stmt = (
        base_stmt.order_by(VASP.name.asc())
        .offset(offset)
        .limit(page_size)
    )
    data_result = await db.execute(data_stmt)
    items: list[VASP] = list(data_result.scalars().all())

    return items, total


# ---------------------------------------------------------------------------
# update_vasp
# ---------------------------------------------------------------------------


async def update_vasp(
    vasp_id: uuid.UUID,
    data: VASPUpdate,
    db: AsyncSession,
) -> VASP:
    """Apply a partial update to a VASP record.

    After updating:
    - Marks all trace_jobs that reference this VASP's addresses with
      needs_reattribution=True (via attributions → clusters → trace_jobs).
    - Publishes a pg_notify "vasp_updated" notification with the vasp_id
      (fire-and-forget; errors are logged but not propagated).

    Requirement 7.2 — admin can update VASP records; triggers reattribution.

    Args:
        vasp_id: UUID of the VASP to update.
        data: Validated VASPUpdate payload (all fields optional).
        db: An open async SQLAlchemy session.

    Returns:
        The updated VASP ORM instance.

    Raises:
        HTTPException(404): VASP not found.
    """
    vasp = await get_vasp(vasp_id, db)

    # Apply partial updates
    if data.name is not None:
        vasp.name = data.name
    if data.category is not None:
        vasp.category = data.category
    if data.jurisdiction is not None:
        vasp.jurisdiction = data.jurisdiction
    if data.operational_status is not None:
        vasp.operational_status = data.operational_status

    await db.flush()

    # Mark affected trace_jobs with needs_reattribution=True.
    # Join path: attributions → clusters → trace_jobs, filtered by vasp_id.
    try:
        reattrib_stmt = text(
            """
            UPDATE trace_jobs
            SET needs_reattribution = TRUE
            WHERE id IN (
                SELECT DISTINCT c.trace_id
                FROM attributions a
                JOIN clusters c ON c.id = a.cluster_id
                WHERE a.vasp_id = :vasp_id
            )
            """
        )
        await db.execute(reattrib_stmt, {"vasp_id": str(vasp_id)})
    except Exception:  # noqa: BLE001
        logger.exception(
            "Failed to mark trace_jobs needs_reattribution for vasp_id=%s", vasp_id
        )

    # Fire-and-forget pg_notify on "vasp_updated" channel
    try:
        notify_stmt = text(
            "SELECT pg_notify('vasp_updated', :payload)"
        )
        await db.execute(notify_stmt, {"payload": str(vasp_id)})
    except Exception:  # noqa: BLE001
        logger.exception(
            "Failed to publish pg_notify vasp_updated for vasp_id=%s", vasp_id
        )

    await db.refresh(vasp)
    return vasp


# ---------------------------------------------------------------------------
# deactivate_vasp
# ---------------------------------------------------------------------------


async def deactivate_vasp(vasp_id: uuid.UUID, db: AsyncSession) -> VASP:
    """Soft-deactivate a VASP by setting operational_status to "inactive".

    Requirement 7.2 — admin can deactivate (soft-delete) VASP records.

    Args:
        vasp_id: UUID of the VASP to deactivate.
        db: An open async SQLAlchemy session.

    Returns:
        The updated VASP ORM instance with status "inactive".

    Raises:
        HTTPException(404): VASP not found.
    """
    vasp = await get_vasp(vasp_id, db)
    vasp.operational_status = "inactive"
    await db.flush()
    await db.refresh(vasp)
    return vasp


# ---------------------------------------------------------------------------
# search_vasps
# ---------------------------------------------------------------------------


async def search_vasps(
    query: str,
    chain: str | None,
    db: AsyncSession,
) -> list[VASP]:
    """Search VASPs by name (ILIKE) or by a known on-chain address.

    If ``chain`` is provided, the address search is restricted to that chain.
    Results are deduplicated (a VASP matched by both name and address appears
    only once).

    Requirement 7.3 — VASP search by name or address.

    Args:
        query: Search term applied as ILIKE %query% on VASP name, and as an
               exact match on vasp_addresses.address.
        chain: Optional blockchain identifier to restrict address lookup.
        db: An open async SQLAlchemy session.

    Returns:
        A list of VASP ORM instances matching the query.
    """
    # Build the address sub-query condition
    addr_subquery = select(VASPAddress.vasp_id).where(
        VASPAddress.address == query
    )
    if chain is not None:
        addr_subquery = addr_subquery.where(VASPAddress.chain == chain)

    stmt = (
        select(VASP)
        .where(
            or_(
                VASP.name.ilike(f"%{query}%"),
                VASP.id.in_(addr_subquery),
            )
        )
        .order_by(VASP.name.asc())
    )

    result = await db.execute(stmt)
    return list(result.scalars().unique().all())
