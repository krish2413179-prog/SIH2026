"""SQLAlchemy ORM model for the unified known-address intelligence table.

Stores tagged blockchain addresses from multiple intelligence sources:
  - OFAC SDN sanctions list
  - Etherscan address labels
  - Bitcoin Abuse community reports
  - Nansen entity labels
  - OpenSanctions aggregated data
  - Manually curated seed data

All models subclass ``Base`` from ``app.db.base`` so Alembic autogenerate
picks them up when this module is imported in ``alembic/env.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class KnownAddress(Base):
    """A blockchain address with a verified intelligence tag.

    Each row represents one (address, chain, source) triple.  The same address
    may appear multiple times if tagged by different sources — downstream
    consumers should pick the highest-confidence tag or merge them.

    ``entity_type`` values:
      - CEX        — centralized exchange (Binance, WazirX, Coinbase …)
      - DEX        — decentralized exchange (Uniswap, PancakeSwap …)
      - mixer      — mixer / tumbler (Tornado Cash, ChipMixer …)
      - bridge     — cross-chain bridge contract (Wormhole, Ronin …)
      - darknet    — darknet marketplace (Hydra, Silk Road …)
      - sanctioned — OFAC / EU / UN sanctioned entity
      - scam       — known scam / phishing address
      - ransomware — ransomware-as-a-service payout wallet
      - other      — uncategorised known entity

    ``source`` values:
      - ofac_sdn, etherscan_labels, bitcoin_abuse, nansen,
        opensanctions, manual
    """

    __tablename__ = "known_addresses"

    __table_args__ = (
        UniqueConstraint(
            "address", "chain", "source",
            name="uq_known_addresses_addr_chain_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    address: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        index=True,
        comment="On-chain address (case-preserved; lookups should lower-case)",
    )
    chain: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Blockchain identifier (ETH, BTC, …). NULL means all chains.",
    )
    entity_name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Human-readable entity name: 'Binance', 'Tornado Cash', …",
    )
    entity_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="CEX | DEX | mixer | bridge | darknet | sanctioned | scam | ransomware | other",
    )
    source: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Intelligence source: ofac_sdn | etherscan_labels | bitcoin_abuse | nansen | opensanctions | manual",
    )
    risk_category: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Optional sub-category: ransomware | terrorism | fraud | sanctions_evasion",
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
        server_default="0.5",
        comment="Confidence score 0.0–1.0 for this tag",
    )
    source_reference: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="URL or ID in the original intelligence source",
    )
    raw_metadata: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Full original record from the intel source for audit trail",
    )
    last_verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="When this tag was last verified against the source",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="When this record was first ingested",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<KnownAddress address={self.address!r} chain={self.chain!r}"
            f" entity={self.entity_name!r} type={self.entity_type!r}"
            f" source={self.source!r} confidence={self.confidence}>"
        )


class VASPMatch(Base):
    """Ranked target VASP / Exchange match result persisted per trace job."""

    __tablename__ = "vasp_matches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    trace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    vasp_address: Mapped[str] = mapped_column(Text, nullable=False)
    vasp_name: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    hops: Mapped[int] = mapped_column(nullable=False)
    path: Mapped[list] = mapped_column(JSONB, nullable=False)
    total_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
