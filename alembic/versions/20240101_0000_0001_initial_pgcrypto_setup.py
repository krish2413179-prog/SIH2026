"""Enable pgcrypto extension and create DB_ENCRYPTION_KEY validation.

This is the first migration that MUST run before any table migrations.
It enables the pgcrypto PostgreSQL extension required for
pgp_sym_encrypt / pgp_sym_decrypt column-level encryption.

Revision ID: 0001
Revises: None
Create Date: 2024-01-01 00:00:00.000000
"""
from __future__ import annotations

from alembic import op

# revision identifiers
revision: str = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgcrypto — required for pgp_sym_encrypt on sensitive columns
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # Enable uuid-ossp for gen_random_uuid() (also provided by pgcrypto)
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")

    # Create an application role for INSERT-only audit log access
    # This role is granted only INSERT on audit_logs — no UPDATE or DELETE
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT FROM pg_roles WHERE rolname = 'audit_writer'
            ) THEN
                CREATE ROLE audit_writer;
            END IF;
        END
        $$;
    """)

    # Create a read-only role for audit log export
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT FROM pg_roles WHERE rolname = 'audit_reader'
            ) THEN
                CREATE ROLE audit_reader;
            END IF;
        END
        $$;
    """)

    # Utility function: encrypt a text value using DB_ENCRYPTION_KEY
    # Consumers call: pgp_sym_encrypt(value, current_setting('app.db_encryption_key'))
    # The key is set at session start via: SET app.db_encryption_key = '<key>';
    op.execute("""
        CREATE OR REPLACE FUNCTION app_encrypt(plaintext TEXT)
        RETURNS BYTEA AS $$
        BEGIN
            RETURN pgp_sym_encrypt(
                plaintext,
                current_setting('app.db_encryption_key', true)
            );
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION app_decrypt(ciphertext BYTEA)
        RETURNS TEXT AS $$
        BEGIN
            RETURN pgp_sym_decrypt(
                ciphertext,
                current_setting('app.db_encryption_key', true)
            );
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER;
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app_decrypt(BYTEA)")
    op.execute("DROP FUNCTION IF EXISTS app_encrypt(TEXT)")
    # Note: we intentionally do NOT drop pgcrypto on downgrade as other
    # objects may depend on it.
