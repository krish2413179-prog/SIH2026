"""Create users, org_units, and jwt_keys tables.

Implements the authentication and key-rotation schema required by:
  - Req 1.1  — JWT-based authentication with configurable expiry
  - Req 1.4  — Three RBAC roles: investigator | supervisor | admin
  - Req 16.1 — bcrypt password storage (column carries the hash)
  - Req 16.6 — Account lockout after 5 failed login attempts
  - Req 16.7 — JWT signing-key rotation without invalidating live tokens

Revision ID: 0002
Revises: 0001
Create Date: 2024-01-02 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Revision metadata
# ---------------------------------------------------------------------------

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. ENUM type: user_role
    # ------------------------------------------------------------------
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE user_role AS ENUM ('investigator', 'supervisor', 'admin');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # ------------------------------------------------------------------
    # 2. org_units — must exist before users (FK target)
    # ------------------------------------------------------------------
    op.create_table(
        "org_units",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_org_units")),
    )

    # ------------------------------------------------------------------
    # 3. users
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column(
            "password_hash",
            sa.String(length=255),
            nullable=False,
            comment="bcrypt hash, cost ≥ 12 (Req 16.1)",
        ),
        sa.Column(
            "role",
            postgresql.ENUM(
                "investigator",
                "supervisor",
                "admin",
                name="user_role",
                create_type=False,   # already created above via op.execute
            ),
            nullable=False,
            comment="RBAC role (Req 1.4)",
        ),
        sa.Column(
            "org_unit_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "failed_login_attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
            comment="Consecutive failed logins; triggers lockout at 5 (Req 16.6)",
        ),
        sa.Column(
            "locked_until",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Account locked until this UTC timestamp (Req 16.6)",
        ),
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
        sa.ForeignKeyConstraint(
            ["org_unit_id"],
            ["org_units.id"],
            name=op.f("fk_users_org_unit_id_org_units"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_org_unit_id"), "users", ["org_unit_id"], unique=False)

    # ------------------------------------------------------------------
    # 4. jwt_keys — rotating signing secrets (Req 16.7)
    # ------------------------------------------------------------------
    op.create_table(
        "jwt_keys",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "key_value",
            sa.Text(),
            nullable=False,
            comment="The signing secret; store encrypted at rest",
        ),
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "valid_until",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="NULL means no scheduled expiry",
        ),
        sa.Column(
            "is_current",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
            comment="Exactly one key is current at any time (Req 16.7)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jwt_keys")),
    )


def downgrade() -> None:
    op.drop_table("jwt_keys")

    op.drop_index(op.f("ix_users_org_unit_id"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")

    op.drop_table("org_units")

    # Drop the custom ENUM type last
    postgresql.ENUM(name="user_role").drop(op.get_bind(), checkfirst=True)
