"""SQLAlchemy ORM models for authentication and authorization.

Covers:
  - OrgUnit  — organisational unit (LEA department/unit)
  - User     — system user with RBAC role and account-lockout support
  - JWTKey   — rotating JWT signing secrets (Req 16.7)

All models use SQLAlchemy 2.x ``mapped_column`` syntax and subclass the
shared ``Base`` from ``app.db.base``, so Alembic autogenerate picks them up
automatically when this module is imported in ``alembic/env.py``.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class UserRole(str, enum.Enum):
    """RBAC roles (Req 1.4)."""

    investigator = "investigator"
    supervisor = "supervisor"
    admin = "admin"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class OrgUnit(Base):
    """Organisational unit — groups users into LEA departments/units.

    Referenced by ``users.org_unit_id`` and ``cases.org_unit_id``.
    """

    __tablename__ = "org_units"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # back-ref populated by User.org_unit
    users: Mapped[list[User]] = relationship("User", back_populates="org_unit")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<OrgUnit id={self.id} name={self.name!r}>"


class User(Base):
    """System user.

    - Passwords stored as bcrypt hashes with cost ≥ 12 (Req 16.1).
    - Role enum enforces RBAC policy (Req 1.4).
    - ``failed_login_attempts`` / ``locked_until`` implement account lockout
      after 5 consecutive failures (Req 16.6).
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="bcrypt hash, cost ≥ 12 (Req 16.1)",
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", create_type=True),
        nullable=False,
        comment="RBAC role: investigator | supervisor | admin (Req 1.4)",
    )
    org_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("org_units.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Account-lockout state (Req 16.6)
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Incremented on each failed login attempt",
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Account locked until this UTC timestamp (Req 16.6)",
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

    # Relationships
    org_unit: Mapped[OrgUnit | None] = relationship(
        "OrgUnit",
        back_populates="users",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User id={self.id} email={self.email!r} role={self.role}>"


class JWTKey(Base):
    """JWT signing key record for key-rotation support (Req 16.7).

    The verification routine selects all rows where ``is_current=True``
    or ``valid_until > now()`` so in-flight tokens survive rotation.
    Only one row should have ``is_current=True`` at any point in time.
    """

    __tablename__ = "jwt_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    key_value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="The signing secret; store encrypted at rest",
    )
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="NULL means the key has no scheduled expiry",
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="Exactly one key should be current at any time (Req 16.7)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<JWTKey id={self.id} is_current={self.is_current}"
            f" valid_from={self.valid_from}>"
        )
