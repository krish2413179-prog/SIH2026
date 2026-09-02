"""SQLAlchemy ORM model for investigation reports.

Covers:
  - Report — generated investigation report (PDF or JSON) linked to a
             case and trace job (Req 11.6)

All models subclass ``Base`` from ``app.db.base`` so Alembic autogenerate
picks them up when this module is imported in ``alembic/env.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class Report(Base):
    """Investigation report generated from a completed trace job (Req 11.6).

    Supports two formats:
      - pdf  — rendered via WeasyPrint; binary stored in object storage
               at the ``s3_key`` path.
      - json — Pydantic-serialised payload stored in the ``json_payload``
               JSONB column.

    Lifecycle (``status``):
      draft              → supervisor-approved

    ``content_hash`` is SHA-256 hex computed over the report payload before
    storage; it is used to detect tampering and forms part of the supervisor
    signature.

    ``supervisor_signature`` format:
      {supervisor_user_id}:{iso_timestamp}:{content_hash}
    """

    __tablename__ = "reports"

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
        comment="Case this report belongs to",
    )
    trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("trace_jobs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Trace job the report was generated from",
    )
    generated_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="User (investigator/supervisor) who triggered report generation",
    )
    format: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="pdf | json",
    )
    s3_key: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Object-storage key for PDF reports; NULL for JSON-only reports",
    )
    json_payload: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Full ReportModel JSON payload; NULL for PDF-only reports",
    )
    content_hash: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="SHA-256 hex of the report payload for tamper detection",
    )
    supervisor_signature: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment=(
            "Supervisor approval signature: "
            "{user_id}:{iso_timestamp}:{content_hash}"
        ),
    )
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="draft",
        comment="draft | supervisor-approved",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp when the report was created",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Report id={self.id} case_id={self.case_id}"
            f" format={self.format!r} status={self.status!r}>"
        )
