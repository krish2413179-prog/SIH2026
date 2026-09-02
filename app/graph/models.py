"""SQLAlchemy ORM models for transaction graph construction.

Covers:
  - TraceJob   — a Celery-backed trace job for a single wallet + chain (Req 5.5)
  - TraceGraph — serialised NetworkX graph stored as JSONB (Req 5.5)

All models subclass ``Base`` from ``app.db.base`` so Alembic autogenerate
picks them up when this module is imported in ``alembic/env.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class TraceJob(Base):
    """A blockchain trace job for one wallet address on one chain.

    Lifecycle: queued → running → completed | failed | rate-limited.
    Progress is tracked via ``current_hop`` / ``estimated_pct`` and updated
    by the Celery worker every 10 seconds (Req 5.5).

    ``needs_reattribution`` is flipped to True by the VASP-update trigger
    when a related VASPAddress row changes, signalling that attributions
    derived from this trace are stale (Req 6.9).
    """

    __tablename__ = "trace_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        # FK to cases(id) — declared here for ORM; enforced by migration
        nullable=False,
        index=True,
        comment="Parent investigation case",
    )
    wallet_address: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Seed wallet address being traced",
    )
    chain: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Blockchain identifier: BTC | ETH | TRX | BSC | SOL | MATIC",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="queued",
        server_default="queued",
        comment="queued | running | completed | failed | rate-limited",
    )
    celery_task_id: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Celery task UUID; NULL until worker picks up the job",
    )
    current_hop: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Last completed graph hop (0-indexed)",
    )
    max_hops: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
        server_default="5",
        comment="Maximum graph traversal depth",
    )
    estimated_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2),
        nullable=True,
        comment="Worker-reported completion percentage 0.00–100.00",
    )

    # Timestamps
    enqueued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="When the job was added to the queue",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the Celery worker picked up the job",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the job reached a terminal state",
    )

    # Risk / reattribution
    needs_reattribution: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="True when a VASP update invalidates derived attributions (Req 6.9)",
    )
    risk_score: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Most recent computed risk score 0–100 (Req 9.4)",
    )
    risk_score_prev: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Previous risk score; delta triggers audit entry (Req 9.4)",
    )
    risk_band: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="low | medium | high derived from risk_score (Req 9.4)",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<TraceJob id={self.id} wallet={self.wallet_address!r}"
            f" chain={self.chain!r} status={self.status!r}>"
        )


class TraceGraph(Base):
    """NetworkX graph serialised as JSONB, linked to a TraceJob.

    ``graph_data`` stores the output of ``networkx.node_link_data(G)`` so the
    graph can be reconstructed without re-running the trace (Req 5.5).
    """

    __tablename__ = "trace_graphs"

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
        comment="Parent trace job",
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        # FK to cases(id) — enforced by migration
        nullable=False,
        index=True,
        comment="Parent investigation case (denormalised for efficient case queries)",
    )
    wallet_address: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Seed wallet address this graph was built from",
    )
    chain: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Blockchain identifier: BTC | ETH | TRX | BSC | SOL | MATIC",
    )
    graph_data: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="networkx.node_link_data(G) serialised as JSONB",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<TraceGraph id={self.id} trace_id={self.trace_id}"
            f" wallet={self.wallet_address!r} chain={self.chain!r}>"
        )
