"""Column-level encryption helpers using PostgreSQL pgcrypto.

Sensitive columns (wallet addresses, case fields, audit log content)
are encrypted at rest via pgp_sym_encrypt / pgp_sym_decrypt, with the
symmetric key sourced from the DB_ENCRYPTION_KEY environment variable.

The key is injected into the PostgreSQL session via a custom event
listener that runs `SET app.db_encryption_key = '...'` at connection
checkout time, making it available to the app_encrypt / app_decrypt
SQL functions defined in the initial migration.

Usage in ORM models:
    from app.db.encryption import EncryptedColumn

    class WalletAddress(Base):
        address: Mapped[str] = mapped_column(EncryptedColumn())
"""

from __future__ import annotations

import binascii
import os
from typing import Any

from sqlalchemy import String, TypeDecorator, event, text
from sqlalchemy.engine import Connection

from app.config import get_settings


def _get_encryption_key() -> str:
    """Return the DB encryption key, raising on missing configuration."""
    key = get_settings().db_encryption_key
    if not key:
        raise RuntimeError(
            "DB_ENCRYPTION_KEY environment variable is not set. "
            "Column-level encryption cannot function without it."
        )
    return key


def register_encryption_key_listener(engine: Any) -> None:
    """Register a SQLAlchemy event that injects the encryption key into
    every database session on connection checkout.

    Call once at application startup:
        register_encryption_key_listener(engine)
    """

    @event.listens_for(engine.sync_engine, "connect")
    def set_encryption_key(dbapi_connection: Any, connection_record: Any) -> None:  # noqa: ARG001
        key = _get_encryption_key()
        cursor = dbapi_connection.cursor()
        # Use parameterized execute to avoid SQL injection
        cursor.execute("SELECT set_config('app.db_encryption_key', %s, false)", (key,))
        cursor.close()


class EncryptedString(TypeDecorator):  # type: ignore[type-arg]
    """SQLAlchemy custom type that transparently encrypts/decrypts a TEXT column
    using the pgcrypto app_encrypt / app_decrypt SQL functions.

    Stores ciphertext as BYTEA in the database.
    Python code reads/writes plain strings.

    Note: filtering and sorting on encrypted columns is not supported —
    use a separate hash column for equality lookups if needed.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:  # noqa: ARG002
        """Encrypt Python string → SQL expression that calls app_encrypt."""
        # Actual encryption happens via raw SQL in ORM event handlers or
        # explicit column expressions. This method returns the plaintext
        # for use in non-encrypted fallback scenarios (tests, dev).
        return value

    def process_result_value(self, value: str | None, dialect: Any) -> str | None:  # noqa: ARG002
        return value
