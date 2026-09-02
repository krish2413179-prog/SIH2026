"""SQLAlchemy ORM models for the VASP registry.

Covers:
  - VASPCategory   — enumerated VASP type classifications
  - VASP           — Virtual Asset Service Provider record (Req 7.1)
  - VASPAddress    — on-chain addresses associated with a VASP (Req 7.1)

All models subclass ``Base`` from ``app.db.base`` so Alembic autogenerate
picks them up when this module is imported in ``alembic/env.py``.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class VASPCategory(str, enum.Enum):
    """Operational category of a Virtual Asset Service Provider."""

    CEX = "CEX"
    DEX = "DEX"
    mixer = "mixer"
    bridge = "bridge"
    darknet = "darknet"
    other = "other"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class VASP(Base):
    """Virtual Asset Service Provider registry entry (Req 7.1).

    ``operational_status`` encodes regulatory / operational state:
      - active     — currently operating
      - inactive   — ceased operations
      - sanctioned — subject to sanctions; triggers high-risk flag
    """

    __tablename__ = "vasps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Full legal / commonly-known name of the VASP",
    )
    category: Mapped[VASPCategory] = mapped_column(
        Enum(VASPCategory, name="vasp_category", create_type=True),
        nullable=False,
        comment="CEX | DEX | mixer | bridge | darknet | other",
    )
    jurisdiction: Mapped[str] = mapped_column(
        String(2),
        nullable=False,
        comment="ISO 3166-1 alpha-2 country code",
    )
    operational_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="active | inactive | sanctioned",
    )
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Timestamp of last registry update",
    )

    # Relationships
    addresses: Mapped[list[VASPAddress]] = relationship(
        "VASPAddress",
        back_populates="vasp",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<VASP id={self.id} name={self.name!r}"
            f" category={self.category} status={self.operational_status!r}>"
        )


class VASPAddress(Base):
    """On-chain address associated with a known VASP (Req 7.1).

    The ``(chain, address)`` pair is unique across the table to prevent
    duplicate address-VASP mappings for the same chain.
    """

    __tablename__ = "vasp_addresses"

    __table_args__ = (
        UniqueConstraint("chain", "address", name="uq_vasp_addresses_chain_address"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    vasp_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("vasps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent VASP record",
    )
    chain: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Blockchain identifier: BTC | ETH | TRX | BSC | SOL | MATIC",
    )
    address: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="On-chain address string (raw, not normalised)",
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Timestamp when this address was added to the registry",
    )

    # Relationships
    vasp: Mapped[VASP] = relationship("VASP", back_populates="addresses")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<VASPAddress id={self.id} chain={self.chain!r}"
            f" address={self.address!r} vasp_id={self.vasp_id}>"
        )
