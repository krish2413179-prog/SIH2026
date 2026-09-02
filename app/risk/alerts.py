"""Risk alert creation and notification helpers.

Provides:
  - create_risk_alert_if_needed — inserts a RiskAlert row and publishes a
    WebSocket broadcast when a trace score enters the high band (≥ 70).
  - notify_risk_score_change    — writes an audit log entry and publishes a
    Redis notification when a trace risk score changes significantly (> 10 pts).

Requirements: 8.4, 8.6
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction, AuditLogEntry
from app.risk.models import RiskAlert
from app.risk.scorer import classify_risk_band

# Channel names for Redis pub/sub
_CHANNEL_RISK_ALERTS = "risk_alerts_broadcast"
_CHANNEL_RISK_CHANGES = "risk_score_changes"


async def create_risk_alert_if_needed(
    trace_id: uuid.UUID,
    case_id: uuid.UUID,
    wallet_address: str,
    risk_score: int,
    db: AsyncSession,
    redis_client: Any | None = None,
) -> RiskAlert | None:
    """Create a RiskAlert row when risk_score is in the high band (≥ 70).

    If the score is below 70 the function returns ``None`` immediately
    without touching the database.

    On a qualifying score the function:
    1. Inserts a ``RiskAlert`` row via ``db.flush()`` (caller is responsible
       for the final ``db.commit()``).
    2. Publishes a JSON broadcast to the ``risk_alerts_broadcast`` Redis
       channel if *redis_client* is provided.

    Args:
        trace_id:       UUID of the trace job that produced the score.
        case_id:        UUID of the parent investigation case.
        wallet_address: Wallet address whose score triggered the alert.
        risk_score:     Integer risk score in [0, 100].
        db:             Active async SQLAlchemy session.
        redis_client:   Optional ``redis.asyncio.Redis`` instance for pub/sub.

    Returns:
        The persisted ``RiskAlert`` ORM object, or ``None`` if no alert was
        needed.

    Requirements: 8.4
    """
    if risk_score < 70:
        return None

    risk_band = classify_risk_band(risk_score)

    alert = RiskAlert(
        trace_id=trace_id,
        case_id=case_id,
        wallet_address=wallet_address,
        risk_score=risk_score,
        risk_band=risk_band,
    )
    db.add(alert)
    await db.flush()

    if redis_client is not None:
        payload = json.dumps(
            {
                "type": "risk_alert",
                "trace_id": str(trace_id),
                "risk_score": risk_score,
                "risk_band": risk_band,
                "wallet_address": wallet_address,
            }
        )
        await redis_client.publish(_CHANNEL_RISK_ALERTS, payload)

    return alert


async def notify_risk_score_change(
    trace_job_id: uuid.UUID,
    new_score: int,
    prev_score: int | None,
    db: AsyncSession,
    redis_client: Any | None = None,
) -> None:
    """Write an audit entry and publish a Redis notification for a significant score change.

    A score change is considered significant when the absolute delta is
    greater than 10 points.  Changes of 10 points or fewer (including the
    case where *prev_score* is ``None``, i.e. an initial scoring) are
    silently ignored.

    On a significant change the function:
    1. Inserts an immutable ``AuditLogEntry`` row recording the before/after
       state (caller is responsible for the final ``db.commit()``).
    2. Publishes a JSON notification to the ``risk_score_changes`` Redis
       channel if *redis_client* is provided.

    Args:
        trace_job_id: UUID of the ``TraceJob`` whose score changed.
        new_score:    The updated risk score.
        prev_score:   The previous risk score, or ``None`` for the initial
                      scoring event.
        db:           Active async SQLAlchemy session.
        redis_client: Optional ``redis.asyncio.Redis`` instance for pub/sub.

    Requirements: 8.6
    """
    if prev_score is None or abs(new_score - prev_score) <= 10:
        return

    audit_entry = AuditLogEntry(
        action_type=AuditAction.trace_completed,
        resource_type="trace_job",
        resource_id=trace_job_id,
        before_state={"risk_score": prev_score},
        after_state={"risk_score": new_score},
        source_ip="system",
        actor_user_id=None,
    )
    db.add(audit_entry)

    if redis_client is not None:
        payload = json.dumps(
            {
                "type": "risk_score_change",
                "trace_job_id": str(trace_job_id),
                "prev_score": prev_score,
                "new_score": new_score,
            }
        )
        await redis_client.publish(_CHANNEL_RISK_CHANGES, payload)
