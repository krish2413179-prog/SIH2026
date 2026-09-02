"""SQLAlchemy declarative base.

All ORM models must import and subclass `Base` from here so that
Alembic autogenerate can detect the full schema.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase, MappedColumn
from sqlalchemy import MetaData

# Naming convention ensures Alembic generates deterministic constraint names
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
