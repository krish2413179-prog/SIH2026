"""OFAC SDN List Ingestion Adapter.

Downloads US Treasury Department OFAC SDN list (XML format) and extracts
all Digital Currency Address entries (XBT/BTC, ETH, TRX, USDT, USDC, etc.),
upserting them into ``known_addresses`` with entity_type="sanctioned" and confidence=1.0.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.intel.models import KnownAddress

logger = logging.getLogger(__name__)

_OFAC_XML_URL = "https://www.treasury.gov/ofac/downloads/sdn.xml"

# Chain abbreviation mapping
_CURRENCY_MAP = {
    "XBT": "BTC",
    "BTC": "BTC",
    "ETH": "ETH",
    "TRX": "TRX",
    "BSC": "BSC",
    "SOL": "SOL",
    "MATIC": "MATIC",
    "USDT": "ETH",
    "USDC": "ETH",
}


async def sync_ofac_sdn(db: AsyncSession) -> int:
    """Fetch and parse the official OFAC SDN XML feed for cryptocurrency addresses.

    Returns the count of crypto entries processed.
    """
    logger.info("sync_ofac_sdn: starting fetch from %s", _OFAC_XML_URL)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(_OFAC_XML_URL)
            resp.raise_for_status()
            xml_content = resp.content
    except Exception as exc:
        logger.error("sync_ofac_sdn: failed to download OFAC XML: %s", exc)
        return 0

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as exc:
        logger.error("sync_ofac_sdn: XML parse error: %s", exc)
        return 0

    # Namespace handling
    ns = {"sdn": "http://www.treasury.gov/ofac/downloads/sdn.xml"}
    # Try finding elements both with namespace and without
    entries = root.findall(".//sdn:sdnEntry", ns) or root.findall(".//sdnEntry")

    count = 0
    for entry in entries:
        # Get entry title / SDN name
        first_name = entry.findtext("sdn:firstName", "", ns) or entry.findtext("firstName", "")
        last_name = entry.findtext("sdn:lastName", "", ns) or entry.findtext("lastName", "")
        title = f"{first_name} {last_name}".strip() or "OFAC Sanctioned Entity"

        # Search idDetails or remarks for crypto addresses
        # OFAC lists crypto addresses under Digital Currency Address features
        id_list = entry.findall(".//sdn:id", ns) or entry.findall(".//id")
        for id_elem in id_list:
            id_type = id_elem.findtext("sdn:idType", "", ns) or id_elem.findtext("idType", "")
            id_number = id_elem.findtext("sdn:idNumber", "", ns) or id_elem.findtext("idNumber", "")

            if "Digital Currency Address" in id_type or "XBT" in id_type or "ETH" in id_type:
                parts = id_number.split()
                if len(parts) >= 2:
                    curr, addr = parts[0], parts[1]
                else:
                    curr, addr = "ETH", id_number

                chain = _CURRENCY_MAP.get(curr.upper(), "ETH")
                clean_addr = addr.strip()

                if not clean_addr:
                    continue

                stmt = (
                    insert(KnownAddress)
                    .values(
                        address=clean_addr,
                        chain=chain,
                        entity_name=f"OFAC: {title}",
                        entity_type="sanctioned",
                        source="ofac_sdn",
                        confidence=1.0,
                        risk_category="sanctions_evasion",
                        source_reference=_OFAC_XML_URL,
                        raw_metadata={"id_type": id_type, "sdn_name": title},
                    )
                    .on_conflict_do_nothing(
                        constraint="uq_known_addresses_addr_chain_source"
                    )
                )
                await db.execute(stmt)
                count += 1

    await db.commit()
    logger.info("sync_ofac_sdn: completed, synced %d crypto addresses", count)
    return count
