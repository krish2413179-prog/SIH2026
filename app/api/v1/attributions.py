"""FastAPI router for VASP attribution endpoints.

Exposes:
  GET /traces/{trace_id}/attributions — list confidence-scored VASP attributions
                                         for a completed trace.

Requirements: 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_investigator
from app.auth.models import User
from app.clustering.models import Attribution, Cluster
from app.db.session import get_db

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
        "Returns an empty list when no attributions exist yet. "
        "Requirements: 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9"
    ),
)
async def get_trace_attributions(
    trace_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_investigator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict[str, Any]]:
    """GET /traces/{trace_id}/attributions — return VASP attributions for a trace.

    Queries Attribution JOIN Cluster filtered by Cluster.trace_id == trace_id.
    Returns an empty list (not 404) when no attributions exist.

    Returns a list of dicts with the keys:

    * ``attribution_id``    — UUID of the Attribution record.
    * ``vasp_id``           — UUID of the attributed VASP.
    * ``confidence_score``  — Confidence score 0.00–100.00.
    * ``low_confidence``    — True when ``confidence_score`` < 40.
    * ``cluster_addresses`` — Addresses in the attributed cluster.
    * ``chain``             — Blockchain chain identifier.
    """
    # Join Attribution → Cluster filtered by trace_id
    result = await db.execute(
        select(Attribution, Cluster)
        .join(Cluster, Attribution.cluster_id == Cluster.id)
        .where(Cluster.trace_id == trace_id)
        .order_by(Attribution.confidence_score.desc())
    )
    rows = result.all()

    # Return empty list when no attributions exist — NOT a 404
    if not rows:
        return []

    output: list[dict[str, Any]] = []
    for attribution, cluster in rows:
        conf_score = float(attribution.confidence_score)
        output.append(
            {
                "attribution_id": str(attribution.id),
                "vasp_id": str(attribution.vasp_id),
                "confidence_score": conf_score,
                "low_confidence": attribution.low_confidence,
                "cluster_addresses": cluster.addresses or [],
                "chain": cluster.chain,
                "cluster_id": str(cluster.id),
            }
        )

    return output
