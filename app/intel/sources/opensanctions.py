"""OpenSanctions Aggregation Adapter.

Queries the free/open OpenSanctions search API for multi-jurisdiction crypto sanctions.
"""

from __future__ import annotations

import logging
import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.intel.models import KnownAddress

logger = logging.getLogger(__name__)

_OPENSANCTIONS_SEARCH_URL = "https://api.opensanctions.org/search/default"


async def check_opensanctions(address: str, db: AsyncSession) -> dict | None:
    """Search OpenSanctions for a wallet address.

    Returns match details if found and persists to ``known_addresses``.
    """
    params = {
        "q": address,
        "schema": "CryptoWallet",
        "limit": 1,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_OPENSANCTIONS_SEARCH_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("check_opensanctions: failed for %s: %s", address[:10], exc)
        return None

    results = data.get("results", [])
    if not results:
        return None

    match = results[0]
    caption = match.get("caption") or "OpenSanctions Listed Wallet"
    properties = match.get("properties", {})
    sanctions = properties.get("sanctions", [])

    stmt = (
        insert(KnownAddress)
        .values(
            address=address,
            chain=None,  # Applies to all chains
            entity_name=f"OpenSanctions: {caption}",
            entity_type="sanctioned",
            source="opensanctions",
            confidence=1.0,
            risk_category="sanctions_evasion",
            source_reference=f"https://www.opensanctions.org/entities/{match.get('id', '')}",
            raw_metadata=match,
        )
        .on_conflict_do_nothing(
            constraint="uq_known_addresses_addr_chain_source"
        )
    )

    await db.execute(stmt)
    await db.commit()

    logger.info("check_opensanctions: found match for %s (%s)", address[:10], caption)
    return match
