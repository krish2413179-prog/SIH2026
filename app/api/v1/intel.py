"""API endpoints for threat intelligence management and address lookup."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.intel.lookup import lookup_address
from app.intel.seed_known_addresses import seed_intel_addresses
from app.intel.sources.nansen import fetch_nansen_address_label
from app.intel.sources.ofac import sync_ofac_sdn

router = APIRouter(prefix="/intel", tags=["Threat Intelligence"])


class KnownAddressResponse(BaseModel):
    id: uuid.UUID
    address: str
    chain: str | None
    entity_name: str
    entity_type: str
    source: str
    confidence: float
    risk_category: str | None

    class Config:
        from_attributes = True


@router.get("/lookup/{address}", response_model=list[KnownAddressResponse])
async def lookup_address_intel(
    address: str,
    chain: str | None = Query(None, description="Optional chain identifier (ETH, BTC, …)"),
    fetch_nansen: bool = Query(True, description="Fetch live label from Nansen if configured"),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Look up a crypto address across all threat intelligence databases.

    Checks local DB (OFAC, Etherscan, seed data, previous lookups) and
    optionally queries live APIs (Nansen) if an API key is available.
    """
    # Optional live Nansen query
    if fetch_nansen and chain:
        await fetch_nansen_address_label(address, chain, db)

    matches = await lookup_address(address, chain, db)
    return matches


@router.post("/seed", status_code=status.HTTP_200_OK)
async def seed_intel_data(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Seed the database with initial known addresses (Indian exchanges, global CEXs, mixers, bridges)."""
    count = await seed_intel_addresses(db)
    return {"status": "success", "seed_count": count}


@router.post("/sync/ofac", status_code=status.HTTP_200_OK)
async def sync_ofac_sanctions(
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Manually trigger a sync with the US Treasury OFAC SDN sanctions list."""
    count = await sync_ofac_sdn(db)
    return {"status": "success", "sanctioned_addresses_synced": count}
