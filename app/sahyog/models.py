"""SQLAlchemy ORM model for SAHYOG Portal submission tracking.

Covers:
  - SAHYOGSubmission — tracks disclosure/freeze requests routed via the
                       SAHYOG Portal (Req 12.3)

All models subclass ``Base`` from ``app.db.base`` so Alembic autogenerate
picks them up when this module is imported in ``alembic/env.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class SAHYOGSubmission(Base):
    """Record of a SAHYOG Portal disclosure or freeze request (Req 12.3).

    Lifecycle:
      pending → acknowledged  (portal acknowledged receipt)
      pending → rejected      (portal rejected the submission)
      pending → failed        (submission could not be delivered after retries)

    ``portal_reference_number`` is populated once the SAHYOG portal returns
    an acknowledgement reference; it is NULL until then.
    """

    __tablename__ = "sahyog_submissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Case this submission belongs to",
    )
    request_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="disclosure | freeze",
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="pending",
        comment="pending | acknowledged | rejected | failed",
    )
    portal_reference_number: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Reference number returned by the SAHYOG portal on acknowledgement",
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp of initial submission",
    )
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="UTC timestamp of last status update",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<SAHYOGSubmission id={self.id} case_id={self.case_id}"
            f" type={self.request_type!r} status={self.status!r}>"
        )
