"""Bitcoin Abuse Database API Integration.

Checks Bitcoin addresses against bitcoinabuse.com API for victim fraud/scam/ransomware reports.
"""

from __future__ import annotations

import logging
import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.intel.models import KnownAddress

logger = logging.getLogger(__name__)

_BITCOIN_ABUSE_API_URL = "https://www.bitcoinabuse.com/api/reports/check"


async def check_bitcoin_abuse(address: str, db: AsyncSession) -> int:
    """Check a BTC address against Bitcoin Abuse API.

    Returns the count of abuse reports found. If > 0, upserts into ``known_addresses``.
    """
    settings = get_settings()
    api_key = settings.bitcoin_abuse_api_key

    params = {"address": address}
    if api_key:
        params["api_token"] = api_key

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_BITCOIN_ABUSE_API_URL, params=params)
            if resp.status_code == 404:
                return 0
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("check_bitcoin_abuse: failed for %s: %s", address[:10], exc)
        return 0

    count = int(data.get("count", 0))
    if count == 0:
        return 0

    # Determine risk category based on recent report descriptions
    reports = data.get("reports", [])
    report_types = [r.get("abuse_type_other", "") for r in reports if isinstance(r, dict)]
    types_str = " ".join(report_types).lower()

    risk_cat = "fraud"
    if "ransomware" in types_str:
        risk_cat = "ransomware"
    elif "darknet" in types_str:
        risk_cat = "darknet"

    stmt = (
        insert(KnownAddress)
        .values(
            address=address,
            chain="BTC",
            entity_name=f"BitcoinAbuse: {count} Reports",
            entity_type="scam",
            source="bitcoin_abuse",
            confidence=min(0.70 + count * 0.05, 0.95),
            risk_category=risk_cat,
            source_reference=f"https://www.bitcoinabuse.com/reports/{address}",
            raw_metadata=data,
        )
        .on_conflict_do_update(
            constraint="uq_known_addresses_addr_chain_source",
            set_={
                "entity_name": f"BitcoinAbuse: {count} Reports",
                "confidence": min(0.70 + count * 0.05, 0.95),
                "raw_metadata": data,
            },
        )
    )

    await db.execute(stmt)
    await db.commit()

    logger.info("check_bitcoin_abuse: address %s has %d reports", address[:10], count)
    return count
