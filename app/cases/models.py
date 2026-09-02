"""SQLAlchemy ORM models for case management.

Covers:
  - CaseStatus  — enum: open | under_review | closed
  - Case         — investigation case with soft-delete support (Req 2.2, 2.3)
  - WalletAddress — a submitted cryptocurrency address (Req 2.4, 3.7)
  - CaseWallet   — many-to-many join between cases and wallet addresses (Req 2.4)

All models subclass ``Base`` from ``app.db.base`` so Alembic autogenerate
picks them up when this module is imported in ``alembic/env.py``.

Encryption note (Req 16.5):
  ``wallet_addresses.address_plain`` stores the raw address for query purposes.
  Full column-level encryption via pgcrypto is enforced at the DB layer by the
  migration; the application layer reads/writes plain text and relies on
  PostgreSQL transparent encryption helpers (``app_encrypt`` / ``app_decrypt``).
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


class CaseStatus(str, enum.Enum):
    """Investigation case lifecycle states (Req 2.3).

    Transitions:
        open → under_review → closed
        under_review → open  (supervisor reopen)
    """

    open = "open"
    under_review = "under_review"
    closed = "closed"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Case(Base):
    """Investigation case managed by LEA investigators / supervisors.

    - Soft-delete via ``deleted_at``; all default queries filter
      ``deleted_at IS NULL`` (Req 2.2).
    - Full-text search via a GIN index on ``to_tsvector('english', …)``
      defined in the migration (Req 2.3).
    - ``org_unit_id`` scopes the case to a department/unit for RBAC
      filtering (Req 1.4).
    """

    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Short case title; included in full-text search index",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Optional detailed description; included in FTS index",
    )
    status: Mapped[CaseStatus] = mapped_column(
        Enum(CaseStatus, name="case_status", create_type=True),
        nullable=False,
        default=CaseStatus.open,
        server_default=CaseStatus.open.value,
        comment="Case lifecycle state: open | under_review | closed (Req 2.3)",
    )

    # Ownership / assignment
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Investigator who opened this case (Req 2.2)",
    )
    supervisor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Assigned supervisor; NULL until explicitly set",
    )
    org_unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("org_units.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Organisational unit scope for RBAC filtering (Req 1.4)",
    )

    # Timestamps
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
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Set on soft-delete; all live queries filter deleted_at IS NULL",
    )

    # Relationships
    case_wallets: Mapped[list[CaseWallet]] = relationship(
        "CaseWallet",
        back_populates="case",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Case id={self.id} title={self.title!r} status={self.status}>"


class WalletAddress(Base):
    """A submitted cryptocurrency wallet address (Req 2.4, 3.7).

    ``address_plain`` holds the raw (unencrypted) address text for efficient
    SQL filtering. The migration adds a GIN/BTREE index on this column.
    ``archived`` is set to True when the owning case is soft-deleted, so
    wallet records are retained but hidden from active queries.
    """

    __tablename__ = "wallet_addresses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    address_plain: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Raw wallet address for DB queries (Req 3.7, 16.5)",
    )
    chain: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Blockchain identifier: BTC | ETH | TRX | BSC | SOL | MATIC",
    )
    submitted_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="User who submitted this address",
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Submission timestamp; used for deduplication window checks",
    )
    archived: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Set to True when the parent case is soft-deleted (Req 2.2)",
    )

    # Relationships
    case_wallets: Mapped[list[CaseWallet]] = relationship(
        "CaseWallet",
        back_populates="wallet_address",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<WalletAddress id={self.id}"
            f" address={self.address_plain!r} chain={self.chain!r}>"
        )


class CaseWallet(Base):
    """Association table linking cases to wallet addresses (Req 2.4).

    Composite primary key on (case_id, wallet_address_id) prevents
    duplicate associations and doubles as an implicit index for
    both FK directions.
    """

    __tablename__ = "case_wallets"

    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    wallet_address_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wallet_addresses.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )

    # Relationships
    case: Mapped[Case] = relationship("Case", back_populates="case_wallets")
    wallet_address: Mapped[WalletAddress] = relationship(
        "WalletAddress",
        back_populates="case_wallets",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<CaseWallet case_id={self.case_id}"
            f" wallet_address_id={self.wallet_address_id}>"
        )
