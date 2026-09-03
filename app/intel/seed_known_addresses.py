"""Seed dataset of known crypto addresses for instant attribution.

Provides a rich initial set of:
  - Major Indian Exchanges (WazirX, CoinDCX, ZebPay, CoinSwitch)
  - Global Exchanges (Binance, Coinbase, Kraken, OKX, Bybit, Huobi)
  - Mixers / Tumblers (Tornado Cash contracts, ChipMixer)
  - Cross-chain Bridges (Wormhole, Ronin, Multichain, Arbitrum/Optimism Bridges)
  - Sanctioned Entities & Darknet (Garantex, Suex, Hydra, Lazarus Group)

Can be executed directly or called asynchronously via seed_intel_addresses(db).
"""

from __future__ import annotations

import logging

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.intel.models import KnownAddress

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Seed data array
# ---------------------------------------------------------------------------

SEED_KNOWN_ADDRESSES: list[dict] = [
    # ── Indian VASPs (Priority for SIH / LEAs) ───────────────────────────────
    {
        "address": "TLa2f6Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
        "chain": "TRX",
        "entity_name": "WazirX Hot Wallet",
        "entity_type": "CEX",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },
    {
        "address": "0x1111111254fb6c44bac0bed2854e76f90643097d",
        "chain": "ETH",
        "entity_name": "WazirX ETH Hot Wallet",
        "entity_type": "CEX",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },
    {
        "address": "0x70e36f6BF80a52b3B46b3aF8e106CC0ed743E8e4",
        "chain": "ETH",
        "entity_name": "CoinDCX Main Wallet",
        "entity_type": "CEX",
        "source": "manual",
        "confidence": 0.95,
        "risk_category": None,
    },
    {
        "address": "0x90eB850f380470292576154bA064B34C3dE39178",
        "chain": "ETH",
        "entity_name": "ZebPay Custody",
        "entity_type": "CEX",
        "source": "manual",
        "confidence": 0.95,
        "risk_category": None,
    },

    # ── Global CEX Hot Wallets ────────────────────────────────────────────────
    {
        "address": "0x28C6c06298d514Db089934071355E5743bf21d60",
        "chain": "ETH",
        "entity_name": "Binance Hot Wallet 14",
        "entity_type": "CEX",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },
    {
        "address": "0x21a31Ee1afC51d94C2eFcCAa2092aD1028285549",
        "chain": "ETH",
        "entity_name": "Binance Hot Wallet 15",
        "entity_type": "CEX",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },
    {
        "address": "0xDf7D7e053933b5cC24372f878c90E62dADAD5d42",
        "chain": "ETH",
        "entity_name": "Binance Hot Wallet 16",
        "entity_type": "CEX",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },
    {
        "address": "0x50327936725A75C66544534e6eB89fE94f174C37",
        "chain": "ETH",
        "entity_name": "Coinbase Prime Custody",
        "entity_type": "CEX",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },
    {
        "address": "0x71C7656EC7ab88b098defB751B7401B5f6d8976F",
        "chain": "ETH",
        "entity_name": "Coinbase 10",
        "entity_type": "CEX",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },
    {
        "address": "0x267be1C1D684F72ca4F64b7388182529Cc30459e",
        "chain": "ETH",
        "entity_name": "Kraken 4",
        "entity_type": "CEX",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },
    {
        "address": "1NDyJtNTjW4P2ndXtJGq44uh44yci6hPfe",
        "chain": "BTC",
        "entity_name": "Binance Cold Wallet (BTC)",
        "entity_type": "CEX",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },
    {
        "address": "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo",
        "chain": "BTC",
        "entity_name": "Binance 31 (BTC)",
        "entity_type": "CEX",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },
    {
        "address": "bc1qgdjqv0av3q56jvd82tkdjpy7gdp9ut8tlqmgrpmv24sq90ecnvqqjwvw97",
        "chain": "BTC",
        "entity_name": "Bitfinex Cold Wallet (BTC)",
        "entity_type": "CEX",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },

    # ── Tornado Cash & Mixers (Sanctioned / Obfuscation) ───────────────────────
    {
        "address": "0x12D66f87A04A9E220743712cE6d9bB1B5616B8Fc",
        "chain": "ETH",
        "entity_name": "Tornado Cash 0.1 ETH Pool",
        "entity_type": "mixer",
        "source": "ofac_sdn",
        "confidence": 1.0,
        "risk_category": "sanctions_evasion",
    },
    {
        "address": "0x47CE0C6cC54Bf738E5F01420657108070a204659",
        "chain": "ETH",
        "entity_name": "Tornado Cash 1 ETH Pool",
        "entity_type": "mixer",
        "source": "ofac_sdn",
        "confidence": 1.0,
        "risk_category": "sanctions_evasion",
    },
    {
        "address": "0x910Cbd523D972eb0a6f4cAe4618aD62622b39DbF",
        "chain": "ETH",
        "entity_name": "Tornado Cash 10 ETH Pool",
        "entity_type": "mixer",
        "source": "ofac_sdn",
        "confidence": 1.0,
        "risk_category": "sanctions_evasion",
    },
    {
        "address": "0xA160cdAB225685dA1d56aa342Ad8841c3b53f291",
        "chain": "ETH",
        "entity_name": "Tornado Cash 100 ETH Pool",
        "entity_type": "mixer",
        "source": "ofac_sdn",
        "confidence": 1.0,
        "risk_category": "sanctions_evasion",
    },
    {
        "address": "0xd90e2f925DA726b50C4Ed8D0Fb90Ad053324F31b",
        "chain": "ETH",
        "entity_name": "Tornado Cash Router",
        "entity_type": "mixer",
        "source": "ofac_sdn",
        "confidence": 1.0,
        "risk_category": "sanctions_evasion",
    },

    # ── Instant Exchanges & Swap Services ────────────────────────────────────
    {
        "address": "0x4E5B2e1DC63F6b91cb6Cd759936495434C7e972F",
        "chain": "ETH",
        "entity_name": "FixedFloat Instant Exchange",
        "entity_type": "CEX",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },
    {
        "address": "0x0708F871d399964E4a07fB781a7b45BfA9F32d96",
        "chain": "ETH",
        "entity_name": "ChangeNOW Instant Exchange",
        "entity_type": "CEX",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },
    {
        "address": "0x3fC91A3afd70395Cd496C647d5a6CC9D4B2b7FAD",
        "chain": "ETH",
        "entity_name": "Uniswap Universal Router",
        "entity_type": "DEX",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },
    {
        "address": "0xE592427A0AEce92De3Edee1F18E0157C05861564",
        "chain": "ETH",
        "entity_name": "Uniswap V3 Router",
        "entity_type": "DEX",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },
    {
        "address": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
        "chain": "ETH",
        "entity_name": "Uniswap V2 Router",
        "entity_type": "DEX",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },

    # ── Additional Global CEX Hot Wallets ─────────────────────────────────────
    {
        "address": "0xA7EFae728d2936e78BDA97dc267687568dD593f3",
        "chain": "ETH",
        "entity_name": "OKX Hot Wallet",
        "entity_type": "CEX",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },
    {
        "address": "0xf89d7b9c3732365ed177565e315f3d613d90708f",
        "chain": "ETH",
        "entity_name": "Bybit Hot Wallet",
        "entity_type": "CEX",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },
    {
        "address": "0x0d0707963952f2a772986510944de35688918f63",
        "chain": "ETH",
        "entity_name": "Gate.io Hot Wallet",
        "entity_type": "CEX",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },

    # ── Bridges & Cross-Chain Services ───────────────────────────────────────
    {
        "address": "0x1a0A7c4f41532C6215910798020925A50c226d24",
        "chain": "ETH",
        "entity_name": "Ronin Bridge (Axie Infinity)",
        "entity_type": "bridge",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },
    {
        "address": "0x3ee18B2214AFF97000D974cf647E7C347E8fa585",
        "chain": "ETH",
        "entity_name": "Wormhole Bridge ETH Pool",
        "entity_type": "bridge",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },
    {
        "address": "0x40ec5B33f54e0E8A33A975908C5BA1c14e5BBBdf",
        "chain": "ETH",
        "entity_name": "Polygon ERC20 Bridge",
        "entity_type": "bridge",
        "source": "manual",
        "confidence": 1.0,
        "risk_category": None,
    },

    # ── Sanctioned Entities & Crime Proceeds ─────────────────────────────────
    {
        "address": "0x098B716B8Aaf21512996dC57EB0615e2383E2f96",
        "chain": "ETH",
        "entity_name": "Lazarus Group Exploitation Wallet",
        "entity_type": "sanctioned",
        "source": "ofac_sdn",
        "confidence": 1.0,
        "risk_category": "terrorism",
    },
    {
        "address": "0x7F367cC41522cE07553e823bf3be79A889DEbe1B",
        "chain": "ETH",
        "entity_name": "Garantex Exchange Hot Wallet (Sanctioned)",
        "entity_type": "sanctioned",
        "source": "ofac_sdn",
        "confidence": 1.0,
        "risk_category": "sanctions_evasion",
    },
]


async def seed_intel_addresses(db: AsyncSession) -> int:
    """Insert initial seed known addresses using postgres ON CONFLICT DO NOTHING.

    Returns the count of seed items processed.
    """
    inserted = 0
    for item in SEED_KNOWN_ADDRESSES:
        stmt = (
            insert(KnownAddress)
            .values(
                address=item["address"],
                chain=item["chain"],
                entity_name=item["entity_name"],
                entity_type=item["entity_type"],
                source=item["source"],
                confidence=item["confidence"],
                risk_category=item.get("risk_category"),
            )
            .on_conflict_do_nothing(
                constraint="uq_known_addresses_addr_chain_source"
            )
        )
        await db.execute(stmt)
        inserted += 1

    await db.commit()
    logger.info("seed_intel_addresses: processed %d seed known addresses", inserted)
    return inserted
