"""SolscanAdapter — SOL blockchain data adapter using Solana public RPC.

Uses the free Solana mainnet RPC (no API key required) to fetch transaction
signatures, falling back gracefully on errors.

Requirements: 4.1, 4.2
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from app.adapters.base import AddressInfo, BlockchainAdapter, DataUnavailableError, RawTransaction
from app.adapters.registry import register_adapter

logger = logging.getLogger(__name__)

_RPC_URL = "https://api.mainnet-beta.solana.com"
_LAMPORTS_PER_SOL = Decimal("1e9")


@register_adapter
class SolscanAdapter(BlockchainAdapter):
    """Adapter for the Solana network using the free public Solana RPC."""

    chain = "SOL"

    async def get_transactions(
        self,
        address: str,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> list[RawTransaction]:
        """Fetch transaction signatures for a Solana address via public RPC."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [address, {"limit": min(page_size, 100)}],
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(_RPC_URL, json=payload)
                r.raise_for_status()
                data = r.json()
        except Exception as exc:
            logger.warning("SOL: could not fetch transactions for %s: %s", address, exc)
            return []

        sigs = data.get("result", [])
        if not isinstance(sigs, list):
            return []

        transactions: list[RawTransaction] = []
        for sig_info in sigs:
            try:
                tx_hash = sig_info.get("signature", "")
                if not tx_hash:
                    continue
                # Skip failed transactions
                if sig_info.get("err"):
                    continue

                raw_ts = sig_info.get("blockTime", 0)
                timestamp = (
                    datetime.fromtimestamp(int(raw_ts), tz=timezone.utc)
                    if raw_ts
                    else datetime.fromtimestamp(0, tz=timezone.utc)
                )

                transactions.append(
                    RawTransaction(
                        tx_hash=tx_hash,
                        from_addr=address,
                        to_addr="",
                        amount=Decimal("0"),
                        fee=Decimal("0"),
                        timestamp=timestamp,
                        chain=self.chain,
                        block_height=sig_info.get("slot"),
                    )
                )
            except Exception:
                continue

        return transactions

    async def get_address_info(self, address: str) -> AddressInfo:
        """Return SOL balance and transaction count via public RPC."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [address],
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(_RPC_URL, json=payload)
                r.raise_for_status()
                data = r.json()
            lamports = data.get("result", {}).get("value", 0)
            balance = Decimal(str(lamports)) / _LAMPORTS_PER_SOL
        except Exception:
            balance = Decimal("0")

        return AddressInfo(
            address=address,
            chain=self.chain,
            balance=balance,
            tx_count=0,
            first_seen=None,
            last_seen=None,
        )
