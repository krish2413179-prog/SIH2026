"""SQLAlchemy ORM model for risk scoring alerts.

Covers:
  - RiskAlert — created when a trace score reaches the 'high' band (≥ 70) (Req 9.4)

All models subclass ``Base`` from ``app.db.base`` so Alembic autogenerate
picks them up when this module is imported in ``alembic/env.py``.

The full risk score is stored on ``trace_jobs.risk_score`` / ``risk_score_prev``.
``RiskAlert`` is a lightweight notification record pushed to supervisors;
it does not replace the score columns on ``TraceJob``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class RiskAlert(Base):
    """Alert record created when a trace risk score enters the 'high' band.

    On score ≥ 70 a ``RiskAlert`` row is inserted and a WebSocket event is
    pushed to the Supervisor's notification channel within the 30-second SLA
    (Celery task → Redis pub/sub → FastAPI WebSocket handler).

    ``notified_supervisor_at`` is set once the WebSocket delivery is confirmed
    so the notification system can detect and retry missed deliveries.
    """

    __tablename__ = "risk_alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        # FK to trace_jobs(id) — enforced by migration
        nullable=False,
        index=True,
        comment="Trace job that triggered this alert",
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        # FK to cases(id) — enforced by migration
        nullable=False,
        index=True,
        comment="Parent case (denormalised for efficient supervisor-scope queries)",
    )
    wallet_address: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Wallet address whose score triggered the alert",
    )
    risk_score: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Risk score at alert time (0–100; ≥ 70 for high band)",
    )
    risk_band: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Risk band label: low | medium | high",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="When this alert was created",
    )
    notified_supervisor_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When WebSocket delivery to Supervisor was confirmed; NULL if pending",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<RiskAlert id={self.id} trace_id={self.trace_id}"
            f" score={self.risk_score} band={self.risk_band!r}>"
        )
