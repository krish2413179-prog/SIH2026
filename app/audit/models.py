"""SQLAlchemy ORM models for audit trail and system monitoring.

Covers:
  - AuditAction          — enumerated loggable event types (Req 14.1)
  - AuditLogEntry        — immutable audit log record (Req 14.1, 14.2, 14.3)
  - SystemAlert          — system health and capacity alerts (Req 14.3)
  - TypologyDefinition   — hot-reloadable typology classifier definitions

Design notes for AuditLogEntry:
  The ``audit_logs`` table is INSERT-only.  Migration 005 explicitly revokes
  UPDATE and DELETE privileges from PUBLIC and from the application role so
  that no application path can modify or erase audit records (Req 14.2).
  Row-level security should be layered on top at the PostgreSQL level.

All models subclass ``Base`` from ``app.db.base`` so Alembic autogenerate
picks them up when this module is imported in ``alembic/env.py``.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AuditAction(str, enum.Enum):
    """All loggable event types for the audit trail (Req 14.1)."""

    # Authentication events
    user_login = "user_login"
    user_logout = "user_logout"
    user_login_failed = "user_login_failed"
    token_refresh = "token_refresh"

    # Case management events
    case_created = "case_created"
    case_updated = "case_updated"
    case_deleted = "case_deleted"
    case_status_changed = "case_status_changed"

    # Wallet and trace events
    wallet_submitted = "wallet_submitted"
    trace_started = "trace_started"
    trace_completed = "trace_completed"

    # Report events
    report_generated = "report_generated"
    report_signed = "report_signed"

    # SAHYOG portal events
    sahyog_submitted = "sahyog_submitted"

    # VASP registry events
    vasp_created = "vasp_created"
    vasp_updated = "vasp_updated"
    vasp_deactivated = "vasp_deactivated"

    # User and role management events
    user_created = "user_created"
    user_updated = "user_updated"
    role_changed = "role_changed"

    # System events
    config_changed = "config_changed"
    audit_export = "audit_export"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class AuditLogEntry(Base):
    """Immutable audit log entry (Req 14.1, 14.2, 14.3).

    This table is append-only by design.  The database migration revokes
    UPDATE and DELETE on this table from PUBLIC and the application role.
    Application code must only ever INSERT; never UPDATE or DELETE rows.

    ``before_state`` and ``after_state`` capture the JSON-serialised resource
    state before and after a mutating action to support forensic review.

    ``actor_user_id`` is nullable to accommodate system-generated events
    (e.g., automated re-attribution) where no human actor is involved.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp of the event; server-generated",
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="User who triggered the action; NULL for system-generated events",
    )
    action_type: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, name="audit_action", create_type=True),
        nullable=False,
        index=True,
        comment="Categorised event type (Req 14.1)",
    )
    resource_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Entity type affected, e.g. 'case', 'user', 'vasp'",
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="Primary key of the affected resource row",
    )
    before_state: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="JSON snapshot of resource state before the action",
    )
    after_state: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="JSON snapshot of resource state after the action",
    )
    source_ip: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Client IP address from the HTTP request",
    )
    session_id: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="JWT jti claim identifying the session, if available",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<AuditLogEntry id={self.id}"
            f" action={self.action_type}"
            f" actor={self.actor_user_id}>"
        )


class SystemAlert(Base):
    """System health and capacity alert record (Req 14.3).

    Created by scheduled monitoring tasks (e.g., audit-log storage at 80%).
    ``resolved`` is flipped to True (with ``resolved_at`` set) once an Admin
    acknowledges or the underlying condition clears.
    """

    __tablename__ = "system_alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    alert_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Machine-readable alert category, e.g. 'storage_high_watermark'",
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Human-readable alert description",
    )
    severity: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="info | warning | critical",
    )
    resolved: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="True once the alert has been resolved",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC timestamp when the alert was resolved; NULL if still open",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<SystemAlert id={self.id} type={self.alert_type!r}"
            f" severity={self.severity!r} resolved={self.resolved}>"
        )


class TypologyDefinition(Base):
    """Hot-reloadable typology classifier definition (Req 9 / design §9).

    Classifier JSON is stored here and loaded into the in-process cache.
    Workers poll for definition changes every 60 seconds using a Redis
    version counter.

    ``typology_name`` is UNIQUE — only one active definition per typology.
    ``uploaded_by`` references ``users.id`` but is nullable to allow
    system-seeded definitions with no human uploader.
    """

    __tablename__ = "typology_definitions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    typology_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        unique=True,
        comment="Unique typology identifier, e.g. 'layering', 'peel_chain'",
    )
    definition_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="Full classifier definition as JSON",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="Incremented on each upload of the same typology",
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Admin user who uploaded this definition; NULL for seeded rows",
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp of this definition version upload",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<TypologyDefinition id={self.id}"
            f" name={self.typology_name!r} v{self.version}>"
        )
