"""FastAPI router for risk scoring endpoints.

Exposes:
  GET /traces/{trace_id}/risk — return risk score, band, and typology tags
                                for a completed trace job.

Requirements: 8.4, 8.6
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_investigator
from app.auth.models import User
from app.db.session import get_db
from app.graph.models import TraceJob
from app.typology.models import TypologyTag

router = APIRouter(prefix="/traces", tags=["risk"])


# ---------------------------------------------------------------------------
# GET /traces/{trace_id}/risk
# ---------------------------------------------------------------------------


@router.get(
    "/{trace_id}/risk",
    summary="Retrieve risk score and typology tags for a trace",
    description=(
        "Returns the risk score, risk band classification, and any detected "
        "typology tags for the TraceJob identified by *trace_id*. "
        "Requires at minimum the investigator role. "
        "Requirements: 8.4, 8.6"
    ),
)
async def get_trace_risk(
    trace_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_investigator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """GET /traces/{trace_id}/risk — return risk score, band, and typology tags.

    Queries ``TraceJob`` for the risk score and band, then queries
    ``TypologyTag`` to collect all typology names detected for this trace.

    Returns a dictionary with the following keys:

    * ``trace_id``       — UUID of the trace job
    * ``wallet_address`` — seed wallet address that was traced
    * ``risk_score``     — integer score in [0, 100], or ``null`` if not yet scored
    * ``risk_band``      — ``low`` | ``medium`` | ``high``, or ``null``
    * ``typology_tags``  — list of detected typology name strings (may be empty)

    Raises:
        HTTPException(404): If no TraceJob exists with the given *trace_id*.

    Requirements: 8.4, 8.6
    """
    # Fetch the TraceJob for risk score and band
    result = await db.execute(
        select(TraceJob).where(TraceJob.id == trace_id)
    )
    job = result.scalars().first()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No trace job found with id {trace_id}",
        )

    # Collect typology tag names for this trace
    tags_result = await db.execute(
        select(TypologyTag.typology).where(TypologyTag.trace_id == trace_id)
    )
    typology_names = list(tags_result.scalars().all())

    return {
        "trace_id": job.id,
        "wallet_address": job.wallet_address,
        "risk_score": job.risk_score,
        "risk_band": job.risk_band,
        "typology_tags": typology_names,
    }
