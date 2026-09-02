"""Admin endpoint for uploading / updating typology definitions.

Exposes:
  POST /admin/typology-definitions — upsert a TypologyDefinition row and
                                      increment the Redis version counter so
                                      workers hot-reload within 60 s.

Requirements: 9.5
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import TypologyDefinition
from app.auth.dependencies import require_admin
from app.auth.models import User
from app.cache.redis import get_redis
from app.db.session import get_db
from app.typology.hot_reload import TYPOLOGY_VERSION_KEY

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/typology-definitions", tags=["admin"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TypologyDefinitionUpload(BaseModel):
    """Request body for creating or updating a typology definition."""

    typology_name: str = Field(
        ...,
        description="Unique typology identifier, e.g. 'layering', 'peel_chain'",
    )
    definition_json: dict[str, Any] = Field(
        ...,
        description="Full classifier definition as an arbitrary JSON object",
    )


class TypologyDefinitionResponse(BaseModel):
    """Response body returned after a successful upsert."""

    id: str
    typology_name: str
    definition_json: dict[str, Any]
    version: int
    uploaded_by: str | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=TypologyDefinitionResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload or update a typology definition",
    description=(
        "Creates a new TypologyDefinition row or updates an existing one "
        "(identified by ``typology_name``). On update the ``version`` field "
        "is incremented by 1.  After persisting the row, the Redis key "
        "``typology_definitions:version`` is incremented so that all workers "
        "detect the change within their next 60-second poll cycle.  "
        "Requires admin role.  "
        "Requirements: 9.5"
    ),
)
async def upload_typology_definition(
    payload: TypologyDefinitionUpload,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> TypologyDefinitionResponse:
    """POST /admin/typology-definitions — upsert a TypologyDefinition.

    * If a row with ``typology_name`` already exists, its ``definition_json``
      and ``version`` are updated in-place (version += 1).
    * If no such row exists, a new row is inserted with ``version = 1``.
    * After the DB write, ``INCR typology_definitions:version`` is sent to
      Redis so workers hot-reload within their next polling interval.

    Args:
        payload: ``typology_name`` + ``definition_json`` from the request body.
        current_user: Authenticated admin user (enforced by ``require_admin``).
        db: Async database session.
        redis_client: Async Redis client.

    Returns:
        The saved ``TypologyDefinition`` serialised as
        ``TypologyDefinitionResponse``.
    """
    # ------------------------------------------------------------------
    # Upsert: look up by typology_name and update or create
    # ------------------------------------------------------------------
    result = await db.execute(
        select(TypologyDefinition).where(
            TypologyDefinition.typology_name == payload.typology_name
        )
    )
    existing: TypologyDefinition | None = result.scalars().first()

    if existing is not None:
        # Update existing row
        existing.definition_json = payload.definition_json
        existing.version = existing.version + 1
        existing.uploaded_by = current_user.id
        definition = existing
        logger.info(
            "Updated typology definition '%s' to version %d by user %s",
            definition.typology_name,
            definition.version,
            current_user.id,
        )
    else:
        # Insert new row
        definition = TypologyDefinition(
            typology_name=payload.typology_name,
            definition_json=payload.definition_json,
            version=1,
            uploaded_by=current_user.id,
        )
        db.add(definition)
        logger.info(
            "Created typology definition '%s' by user %s",
            definition.typology_name,
            current_user.id,
        )

    # Flush to get the generated id/timestamps back before we need them
    await db.flush()

    # ------------------------------------------------------------------
    # Increment Redis version counter so workers hot-reload
    # ------------------------------------------------------------------
    new_redis_version = await redis_client.incr(TYPOLOGY_VERSION_KEY)
    logger.info(
        "Incremented Redis typology version counter to %d", new_redis_version
    )

    # Build response (flush already resolved server defaults)
    return TypologyDefinitionResponse(
        id=str(definition.id),
        typology_name=definition.typology_name,
        definition_json=definition.definition_json,
        version=definition.version,
        uploaded_by=str(definition.uploaded_by) if definition.uploaded_by else None,
    )
