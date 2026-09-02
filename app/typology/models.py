"""SQLAlchemy ORM model for typology detection results.

Covers:
  - TypologyTag — a detected laundering pattern tag on a specific address (Req 9.4)

All models subclass ``Base`` from ``app.db.base`` so Alembic autogenerate
picks them up when this module is imported in ``alembic/env.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class TypologyTag(Base):
    """A typology detection result for a specific address within a trace.

    Each ``TypologyDetector`` that fires produces one ``TypologyTag`` row.
    Only detections with ``match_confidence >= 0.60`` are persisted
    (threshold enforced by the ``TypologyClassifier``).

    ``sub_graph`` optionally stores the triggering sub-graph fragment as
    ``networkx.node_link_data(sub_G)`` JSONB for evidence display in the
    report and graph viewer (Req 9.4).
    """

    __tablename__ = "typology_tags"

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
        comment="Trace job that produced this detection",
    )
    address: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Address on which the typology was detected",
    )
    typology: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment=(
            "Typology label: layering | peel_chain | mixer | bridge_abuse"
            " | darknet | ransomware | fraud_aggregation"
        ),
    )
    match_confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        comment="Detector confidence 0.0000–1.0000; only ≥ 0.60 are stored",
    )
    sub_graph: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="networkx.node_link_data of the triggering sub-graph fragment",
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="When this typology tag was created",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<TypologyTag id={self.id} trace_id={self.trace_id}"
            f" typology={self.typology!r} confidence={self.match_confidence}>"
        )
