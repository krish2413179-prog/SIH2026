"""FastAPI router for wallet address submission.

Exposes the batch wallet submission endpoint:
  POST /cases/{case_id}/wallets

Requirements: 3.1, 3.4, 3.5, 3.6, 3.7
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_investigator
from app.auth.models import User
from app.db.session import get_db
from app.graph.models import TraceJob
from app.wallets import service
from app.wallets.schemas import WalletSubmitBatch, WalletSubmitResponse

router = APIRouter(tags=["wallets"])


@router.get(
    "/cases/{case_id}/wallets",
    summary="List trace jobs for a case",
)
async def list_case_wallets(
    case_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_investigator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict[str, Any]]:
    """GET /cases/{case_id}/wallets — return trace jobs linked to a case."""
    result = await db.execute(
        select(TraceJob).where(TraceJob.case_id == case_id).order_by(TraceJob.enqueued_at.desc())
    )
    jobs = result.scalars().all()
    return [
        {
            "id": str(j.id),
            "trace_id": str(j.id),
            "wallet_address": j.wallet_address,
            "chain": j.chain,
            "status": j.status,
            "current_hop": j.current_hop,
            "max_hops": j.max_hops,
            "estimated_pct": float(j.estimated_pct) if j.estimated_pct else None,
            "enqueued_at": j.enqueued_at.isoformat() if j.enqueued_at else None,
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            "risk_score": j.risk_score,
            "risk_band": j.risk_band,
        }
        for j in jobs
    ]


# ---------------------------------------------------------------------------
# POST /cases/{case_id}/wallets — batch wallet submission
# ---------------------------------------------------------------------------


@router.post(
    "/cases/{case_id}/wallets",
    response_model=WalletSubmitResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit wallet addresses for a case",
    description=(
        "Submit a batch of up to 50 wallet addresses for investigation under a case. "
        "Supported chains: BTC, ETH, TRX, BSC, SOL, MATIC. "
        "Addresses not matching any supported chain format are returned in the errors list. "
        "Duplicate submissions within a 24-hour window reuse the existing trace job. "
        "Each valid (address, chain) pair creates a TraceJob and enqueues a Celery worker. "
        "Requirements: 3.1, 3.4, 3.5, 3.6, 3.7"
    ),
)
async def submit_wallets(
    case_id: uuid.UUID,
    batch: WalletSubmitBatch,
    current_user: Annotated[User, Depends(require_investigator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WalletSubmitResponse:
    """POST /cases/{case_id}/wallets — batch wallet address submission.

    Requires at minimum the investigator role. Accepts 1–50 wallet address
    items per request. Returns successfully queued results and per-item errors.
    """
    return await service.submit_wallets(
        case_id=case_id,
        batch=batch,
        submitted_by=current_user,
        db=db,
    )
