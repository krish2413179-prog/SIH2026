"""FastAPI router for VASP attribution endpoints.

Exposes:
  GET /traces/{trace_id}/attributions — list confidence-scored VASP attributions
                                         for a completed trace.

Requirements: 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_investigator
from app.auth.models import User
from app.clustering.models import Attribution, Cluster as ClusterModel
from app.db.session import get_db
from app.vasp_db.models import VASP

router = APIRouter(prefix="/traces", tags=["attributions"])


# ---------------------------------------------------------------------------
# GET /traces/{trace_id}/attributions
# ---------------------------------------------------------------------------


@router.get(
    "/{trace_id}/attributions",
    summary="List VASP attributions for a trace",
    description=(
        "Returns all confidence-scored VASP attributions produced by the "
        "attribution pipeline for the trace identified by *trace_id*. "
        "Each item includes the attribution id, VASP metadata, confidence score, "
        "a low-confidence flag, and the list of cluster addresses. "
        "Requires at minimum the investigator role. "
        "Requirements: 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9"
    ),
)
async def get_trace_attributions(
    trace_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_investigator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict[str, Any]]:
    """GET /traces/{trace_id}/attributions — return VASP attributions for a trace.

    Queries Attribution rows whose parent Cluster belongs to *trace_id*, then
    joins with VASP to return human-readable VASP metadata alongside the
    attribution confidence.

    Returns a list of dicts with the keys:

    * ``attribution_id``    — UUID of the Attribution record.
    * ``vasp_name``         — Full name of the attributed VASP.
    * ``vasp_category``     — VASP category: CEX | DEX | mixer | bridge | darknet | other.
    * ``confidence_score``  — Weighted attribution score 0.00–100.00.
    * ``low_confidence``    — True when ``confidence_score`` < 40.
    * ``cluster_addresses`` — List of address strings in the attributed cluster.

    Raises:
        HTTPException(404): If no attributions exist for *trace_id*.

    Requirements: 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9
    """
    # Join Attribution → Cluster (filtered by trace_id) → VASP
    result = await db.execute(
        select(Attribution, ClusterModel, VASP)
        .join(ClusterModel, Attribution.cluster_id == ClusterModel.id)
        .join(VASP, Attribution.vasp_id == VASP.id)
        .where(ClusterModel.trace_id == trace_id)
        .order_by(Attribution.confidence_score.desc())
    )
    rows = result.all()

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No attributions found for trace_id {trace_id}",
        )

    output: list[dict[str, Any]] = []
    for attribution, cluster, vasp in rows:
        vasp_category_str = (
            vasp.category.value
            if hasattr(vasp.category, "value")
            else str(vasp.category)
        )
        output.append(
            {
                "attribution_id": attribution.id,
                "vasp_name": vasp.name,
                "vasp_category": vasp_category_str,
                "confidence_score": float(attribution.confidence_score),
                "low_confidence": attribution.low_confidence,
                "cluster_addresses": cluster.addresses,  # already a list from JSONB
            }
        )

    return output
