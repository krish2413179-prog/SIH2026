"""Alembic environment configuration.

Reads DATABASE_SYNC_URL from environment (or .env file) so that
`alembic upgrade head` works both locally and in Docker.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from dotenv import load_dotenv

# Load .env file for local development
load_dotenv()

# Alembic Config object (gives access to values in alembic.ini)
config = context.config

# Use DATABASE_SYNC_URL or DATABASE_URL env var if set
database_url = os.environ.get("DATABASE_SYNC_URL") or os.environ.get("DATABASE_URL")
if database_url:
    database_url = database_url.replace(
        "postgresql+asyncpg://", "postgresql+psycopg://"
    ).replace("postgresql+psycopg2://", "postgresql+psycopg://").replace(
        "postgresql://", "postgresql+psycopg://"
    )

# Configure Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import all models so Alembic can detect schema changes via autogenerate
# This import is intentionally deferred to avoid circular imports at migration time
try:
    from app.db.base import Base  # noqa: F401  — registers all ORM models

    # Auth models — users, org_units, jwt_keys
    import app.auth.models  # noqa: F401

    # Case management models — cases, wallet_addresses, case_wallets
    import app.cases.models  # noqa: F401

    # Graph models — trace_jobs, trace_graphs
    import app.graph.models  # noqa: F401

    # Clustering models — clusters, attributions
    import app.clustering.models  # noqa: F401

    # Typology models — typology_tags
    import app.typology.models  # noqa: F401

    # Risk models — risk_alerts
    import app.risk.models  # noqa: F401

    # VASP registry models — vasps, vasp_addresses
    import app.vasp_db.models  # noqa: F401

    # SAHYOG Portal submission tracking models
    import app.sahyog.models  # noqa: F401

    # Report models — reports
    import app.reports.models  # noqa: F401

    # Audit trail models — audit_logs, system_alerts, typology_definitions
    import app.audit.models  # noqa: F401

    target_metadata = Base.metadata
except ImportError:
    # Graceful fallback before app package is installed
    target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no DB connection required)."""
    url = database_url or config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (executes directly against the DB)."""
    from sqlalchemy import create_engine

    if database_url:
        connectable = create_engine(database_url, poolclass=pool.NullPool)
    else:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
