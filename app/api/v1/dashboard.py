"""Dashboard summary and alerts endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

from app.auth.dependencies import require_investigator
from app.auth.models import User
from app.cases.models import Case
from app.db.session import get_db
from app.graph.models import TraceJob
from app.risk.models import RiskAlert

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
async def dashboard_summary(
    current_user: User = Depends(require_investigator),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return high-level case and trace statistics for the dashboard."""
    # Total open cases
    open_result = await db.execute(
        select(func.count()).select_from(Case).where(
            Case.status == "open", Case.deleted_at.is_(None)
        )
    )
    open_cases = open_result.scalar_one() or 0

    # Active (running/queued) traces
    active_result = await db.execute(
        select(func.count()).select_from(TraceJob).where(
            TraceJob.status.in_(["queued", "running"])
        )
    )
    active_traces = active_result.scalar_one() or 0

    # High-risk alerts (risk_score >= 70)
    high_risk_result = await db.execute(
        select(func.count()).select_from(RiskAlert)
    )
    high_risk_cases = high_risk_result.scalar_one() or 0

    return {
        "open_cases": open_cases,
        "active_traces": active_traces,
        "high_risk_cases": high_risk_cases,
        "pending_sahyog": 0,
    }


@router.get("/alerts")
async def dashboard_alerts(
    current_user: User = Depends(require_investigator),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return recent high-risk alerts."""
    result = await db.execute(
        select(RiskAlert).order_by(RiskAlert.created_at.desc()).limit(20)
    )
    alerts = result.scalars().all()
    return [
        {
            "id": str(a.id),
            "type": "risk_alert",
            "message": f"High risk score {a.risk_score} ({a.risk_band}) for wallet {a.wallet_address}",
            "severity": "high" if a.risk_score >= 70 else "medium",
            "timestamp": a.created_at.isoformat(),
        }
        for a in alerts
    ]


@router.get("/pending-approvals")
async def pending_approvals(
    current_user: User = Depends(require_investigator),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return reports pending supervisor approval."""
    from app.reports.models import Report
    result = await db.execute(
        select(Report).where(Report.status == "draft").order_by(Report.created_at.desc()).limit(20)
    )
    reports = result.scalars().all()
    return [
        {
            "report_id": str(r.id),
            "case_id": str(r.case_id),
            "format": r.format,
            "created_at": r.created_at.isoformat(),
        }
        for r in reports
    ]
