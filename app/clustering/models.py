"""SQLAlchemy ORM models for address clustering and VASP attribution.

Covers:
  - Cluster     — a set of co-owned addresses identified by on-chain heuristics (Req 6.9)
  - Attribution — confidence-scored link between a Cluster and a known VASP (Req 6.9)

All models subclass ``Base`` from ``app.db.base`` so Alembic autogenerate
picks them up when this module is imported in ``alembic/env.py``.

Note on ``Attribution.low_confidence``:
  This field is computed in Python (``confidence_score < 40``) before
  persistence — it is NOT a database-generated column. This keeps the
  model compatible with all PostgreSQL versions and avoids the complexity
  of SQLAlchemy's ``Computed`` type.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class Cluster(Base):
    """A set of blockchain addresses inferred to share a single owner.

    Produced by either:
    - Common-Input Ownership (CIO) heuristic — Bitcoin
    - Deposit-address pattern — EVM chains, TRX, SOL

    ``addresses`` is a JSONB array of raw address strings so the full
    cluster can be retrieved in a single column without joining.
    """

    __tablename__ = "clusters"

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
        comment="Trace job that produced this cluster",
    )
    chain: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Blockchain identifier: BTC | ETH | TRX | BSC | SOL | MATIC",
    )
    addresses: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        comment="JSON array of address strings belonging to this cluster",
    )
    cluster_method: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Heuristic used: cio | deposit_pattern",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Cluster id={self.id} chain={self.chain!r}"
            f" method={self.cluster_method!r}>"
        )


class Attribution(Base):
    """Confidence-scored attribution of a Cluster to a known VASP (Req 6.9).

    ``vasp_id`` references ``vasps.id`` but the FK constraint is intentionally
    omitted here — it is added in migration 005 after the ``vasps`` table is
    created.  This allows migration 004 to run independently of the VASP
    registry migration.

    ``low_confidence`` must be set in Python before inserting/updating:
        attribution.low_confidence = attribution.confidence_score < 40
    It is NOT a database-generated column.
    """

    __tablename__ = "attributions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        # FK to clusters(id) — enforced by migration
        nullable=False,
        index=True,
        comment="Cluster this attribution belongs to",
    )
    vasp_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        # FK to vasps(id) added in migration 005 — NOT present in migration 004
        nullable=False,
        index=True,
        comment="Identified VASP; FK added in migration 005",
    )
    confidence_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        comment="Overall attribution confidence 0.00–100.00",
    )
    low_confidence: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="True when confidence_score < 40; set in Python before persist",
    )

    # Component sub-scores (all optional — not available for every method)
    address_match_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4),
        nullable=True,
        comment="matched addresses / total cluster size",
    )
    volume_similarity: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4),
        nullable=True,
        comment="0–1 cosine similarity of volume vectors",
    )
    behavioral_similarity: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4),
        nullable=True,
        comment="0–1 pattern match score",
    )
    temporal_proximity: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4),
        nullable=True,
        comment="0–1 recency weight",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Attribution id={self.id} cluster_id={self.cluster_id}"
            f" vasp_id={self.vasp_id} score={self.confidence_score}>"
        )
