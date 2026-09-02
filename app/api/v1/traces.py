"""FastAPI router for trace graph and status endpoints.

Exposes:
  GET /traces/{trace_id}/graph   — return serialised graph data for a completed trace
  GET /traces/{trace_id}/status  — return current status/progress of a trace job

Requirements: 5.5, 15.4
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
from app.graph.models import TraceGraph, TraceJob

router = APIRouter(prefix="/traces", tags=["traces"])


# ---------------------------------------------------------------------------
# GET /traces/{trace_id}/graph
# ---------------------------------------------------------------------------


@router.get(
    "/{trace_id}/graph",
    summary="Retrieve serialised transaction graph for a trace",
    description=(
        "Returns the NetworkX node-link JSON representation of the transaction graph "
        "built during the trace job identified by *trace_id*. "
        "Requires at minimum the investigator role. "
        "Requirements: 5.5"
    ),
)
async def get_trace_graph(
    trace_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_investigator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """GET /traces/{trace_id}/graph — return raw graph_data JSON.

    Returns the stored ``node_link_data`` dictionary directly so the caller
    can reconstruct the graph client-side or pass it to a visualisation layer.

    Raises:
        HTTPException(404): If no graph has been persisted for *trace_id*.
    """
    result = await db.execute(
        select(TraceGraph).where(TraceGraph.trace_id == trace_id)
    )
    record = result.scalars().first()

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No graph found for trace_id {trace_id}",
        )

    return record.graph_data


# ---------------------------------------------------------------------------
# GET /traces/{trace_id}/status
# ---------------------------------------------------------------------------


@router.get(
    "/{trace_id}/status",
    summary="Retrieve the current status of a trace job",
    description=(
        "Returns progress and risk metadata for the TraceJob identified by *trace_id*. "
        "Requires at minimum the investigator role. "
        "Requirements: 5.5, 15.4"
    ),
)
async def get_trace_status(
    trace_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_investigator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """GET /traces/{trace_id}/status — return trace job progress and risk fields.

    Returns a dictionary with the following keys:

    * ``trace_id``      — UUID of the trace job
    * ``status``        — lifecycle state: queued | running | completed | failed | rate-limited
    * ``current_hop``   — last completed BFS hop (0-indexed)
    * ``max_hops``      — configured maximum traversal depth
    * ``estimated_pct`` — worker-reported completion percentage (0–100), or null
    * ``enqueued_at``   — ISO timestamp when the job was queued
    * ``started_at``    — ISO timestamp when the worker picked up the job, or null
    * ``completed_at``  — ISO timestamp when the job reached a terminal state, or null
    * ``risk_score``    — most recent risk score (0–100), or null
    * ``risk_band``     — low | medium | high, or null

    Raises:
        HTTPException(404): If no TraceJob exists with the given *trace_id*.
    """
    result = await db.execute(
        select(TraceJob).where(TraceJob.id == trace_id)
    )
    job = result.scalars().first()

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No trace job found with id {trace_id}",
        )

    return {
        "trace_id": job.id,
        "status": job.status,
        "current_hop": job.current_hop,
        "max_hops": job.max_hops,
        "estimated_pct": job.estimated_pct,
        "enqueued_at": job.enqueued_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "risk_score": job.risk_score,
        "risk_band": job.risk_band,
    }
