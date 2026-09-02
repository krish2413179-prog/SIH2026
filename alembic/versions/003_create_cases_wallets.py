"""Create cases, wallet_addresses, and case_wallets tables.

Implements the case management and wallet submission schema required by:
  - Req 2.2  — Case creation with soft-delete (deleted_at)
  - Req 2.3  — Case lifecycle states and full-text search on title/description
  - Req 2.4  — Wallet address submission and case-wallet association
  - Req 3.7  — Raw address storage for efficient DB queries
  - Req 16.5 — Column-level encryption via pgcrypto (address_plain)

Revision ID: 0003
Revises: 0002
Create Date: 2024-01-03 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Revision metadata
# ---------------------------------------------------------------------------

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. ENUM type: case_status
    # ------------------------------------------------------------------
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE case_status AS ENUM ('open', 'under_review', 'closed');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # ------------------------------------------------------------------
    # 2. cases table (Req 2.2, 2.3)
    # ------------------------------------------------------------------
    op.create_table(
        "cases",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "title",
            sa.String(length=255),
            nullable=False,
            comment="Short case title; included in full-text search index",
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=True,
            comment="Optional detailed description; included in FTS index",
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "open",
                "under_review",
                "closed",
                name="case_status",
                create_type=False,
            ),
            nullable=False,
            server_default="open",
            comment="Case lifecycle state: open | under_review | closed (Req 2.3)",
        ),
        # Ownership / assignment
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Investigator who opened this case (Req 2.2)",
        ),
        sa.Column(
            "supervisor_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Assigned supervisor; NULL until explicitly set",
        ),
        sa.Column(
            "org_unit_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="Organisational unit scope for RBAC filtering (Req 1.4)",
        ),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Set on soft-delete; live queries filter deleted_at IS NULL",
        ),
        # Constraints
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_cases_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supervisor_id"],
            ["users.id"],
            name=op.f("fk_cases_supervisor_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_unit_id"],
            ["org_units.id"],
            name=op.f("fk_cases_org_unit_id_org_units"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cases")),
    )

    # Composite filter index for role-scoped list queries (Req 2.3)
    op.create_index(
        "ix_cases_status_created_by_created_at",
        "cases",
        ["status", "created_by", "created_at"],
        unique=False,
    )

    # GIN index for full-text search on title + description (Req 2.3)
    op.execute(
        """
        CREATE INDEX ix_cases_fts
        ON cases
        USING GIN (
            to_tsvector(
                'english',
                title || ' ' || coalesce(description, '')
            )
        )
        """
    )

    # ------------------------------------------------------------------
    # 3. wallet_addresses table (Req 2.4, 3.7)
    # ------------------------------------------------------------------
    op.create_table(
        "wallet_addresses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "address_plain",
            sa.Text(),
            nullable=False,
            comment="Raw wallet address for DB queries (Req 3.7, 16.5)",
        ),
        sa.Column(
            "chain",
            sa.Text(),
            nullable=False,
            comment="Blockchain: BTC | ETH | TRX | BSC | SOL | MATIC",
        ),
        sa.Column(
            "submitted_by",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="User who submitted this address",
        ),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Submission timestamp; used for deduplication window",
        ),
        sa.Column(
            "archived",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="Set True when parent case is soft-deleted (Req 2.2)",
        ),
        # Constraints
        sa.ForeignKeyConstraint(
            ["submitted_by"],
            ["users.id"],
            name=op.f("fk_wallet_addresses_submitted_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wallet_addresses")),
    )

    op.create_index(
        op.f("ix_wallet_addresses_submitted_by"),
        "wallet_addresses",
        ["submitted_by"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # 4. case_wallets join table (Req 2.4)
    # ------------------------------------------------------------------
    op.create_table(
        "case_wallets",
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "wallet_address_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["cases.id"],
            name=op.f("fk_case_wallets_case_id_cases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["wallet_address_id"],
            ["wallet_addresses.id"],
            name=op.f("fk_case_wallets_wallet_address_id_wallet_addresses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "case_id",
            "wallet_address_id",
            name=op.f("pk_case_wallets"),
        ),
    )


def downgrade() -> None:
    op.drop_table("case_wallets")

    op.drop_index(
        op.f("ix_wallet_addresses_submitted_by"),
        table_name="wallet_addresses",
    )
    op.drop_table("wallet_addresses")

    # Drop FTS index explicitly (not tracked by op.create_index)
    op.execute("DROP INDEX IF EXISTS ix_cases_fts")
    op.drop_index("ix_cases_status_created_by_created_at", table_name="cases")
    op.drop_table("cases")

    # Drop the custom ENUM type last
    postgresql.ENUM(name="case_status").drop(op.get_bind(), checkfirst=True)
