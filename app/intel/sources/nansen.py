"""Nansen API Integration Adapter.

Utilizes Nansen's wallet attribution & intelligence API (using config.nansen_api_key)
to look up entity labels, labels (e.g. 'Binance Deposit', 'DeFi User', 'Smart Money'),
and risk attributes for addresses during tracing or background sync.
"""

from __future__ import annotations

import logging
import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.intel.models import KnownAddress

logger = logging.getLogger(__name__)

_NANSEN_BASE_URL = "https://api.nansen.ai/v1"


def _map_nansen_category(category: str, labels: list[str]) -> str:
    """Map Nansen category and labels to internal entity_type."""
    cat_lower = category.lower()
    labels_str = " ".join(labels).lower()

    if "exchange" in cat_lower or "cex" in cat_lower or "binance" in labels_str or "coinbase" in labels_str:
        return "CEX"
    if "dex" in cat_lower or "uniswap" in labels_str or "sushi" in labels_str:
        return "DEX"
    if "mixer" in cat_lower or "tornado" in labels_str:
        return "mixer"
    if "bridge" in cat_lower:
        return "bridge"
    if "scam" in labels_str or "phishing" in labels_str or "exploit" in labels_str:
        return "scam"
    if "darknet" in labels_str:
        return "darknet"
    return "other"


async def fetch_nansen_address_label(
    address: str,
    chain: str,
    db: AsyncSession,
) -> KnownAddress | None:
    """Fetch wallet label and entity info for a single address from Nansen API.

    If found, upserts the record into ``known_addresses`` with source="nansen"
    and confidence=0.90.
    """
    settings = get_settings()
    api_key = settings.nansen_api_key

    if not api_key:
        logger.debug("fetch_nansen_address_label: NANSEN_API_KEY not configured — skipping")
        return None

    headers = {
        "api-key": api_key,
        "Accept": "application/json",
    }

    url = f"{_NANSEN_BASE_URL}/address/{address}/metadata"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("fetch_nansen_address_label: request failed for %s: %s", address[:10], exc)
        return None

    entity_name = data.get("entity_name") or data.get("label") or "Nansen Labelled Wallet"
    category = data.get("category", "")
    labels = data.get("labels", [])

    entity_type = _map_nansen_category(category, labels)

    stmt = (
        insert(KnownAddress)
        .values(
            address=address,
            chain=chain.upper(),
            entity_name=entity_name,
            entity_type=entity_type,
            source="nansen",
            confidence=0.90,
            source_reference=url,
            raw_metadata=data,
        )
        .on_conflict_do_update(
            constraint="uq_known_addresses_addr_chain_source",
            set_={
                "entity_name": entity_name,
                "entity_type": entity_type,
                "confidence": 0.90,
                "raw_metadata": data,
            },
        )
    )

    await db.execute(stmt)
    await db.commit()

    logger.info("fetch_nansen_address_label: tagged %s as %s (%s)", address[:10], entity_name, entity_type)
    return KnownAddress(
        address=address,
        chain=chain,
        entity_name=entity_name,
        entity_type=entity_type,
        source="nansen",
        confidence=0.90,
    )
