"""006 — Create known_addresses and vasp_matches tables.

Revision ID: 006
Revises: 005
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── known_addresses ────────────────────────────────────────────────────
    op.create_table(
        "known_addresses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("address", sa.Text(), nullable=False, index=True),
        sa.Column("chain", sa.Text(), nullable=True),
        sa.Column("entity_name", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("risk_category", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("raw_metadata", JSONB(), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("address", "chain", "source", name="uq_known_addresses_addr_chain_source"),
    )
    # Additional index for fast case-insensitive lookups
    op.create_index(
        "ix_known_addresses_address_lower",
        "known_addresses",
        [sa.text("lower(address)")],
    )

    # ── vasp_matches — persists nearest-VASP results per trace ─────────
    op.create_table(
        "vasp_matches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("trace_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("case_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("vasp_address", sa.Text(), nullable=False),
        sa.Column("vasp_name", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("hops", sa.Integer(), nullable=False),
        sa.Column("path", JSONB(), nullable=False, comment="Ordered list of wallet addresses from seed to VASP"),
        sa.Column("total_value", sa.Float(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("source", sa.Text(), nullable=False, comment="Intel source that tagged the VASP address"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["trace_id"], ["trace_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("vasp_matches")
    op.drop_index("ix_known_addresses_address_lower", table_name="known_addresses")
    op.drop_table("known_addresses")
