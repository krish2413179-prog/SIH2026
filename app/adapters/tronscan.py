"""TronscanAdapter — TRX blockchain data adapter using Tronscan API.

Requirements: 4.1, 4.2
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from app.adapters.base import AddressInfo, BlockchainAdapter, DataUnavailableError, RawTransaction
from app.adapters.registry import register_adapter

logger = logging.getLogger(__name__)

_BASE_URL = "https://apilist.tronscan.org/api"

# TRX uses SUN as the base unit (1 TRX = 1_000_000 SUN)
_SUN_PER_TRX = Decimal("1e6")


@register_adapter
class TronscanAdapter(BlockchainAdapter):
    """Adapter for the TRON network via Tronscan public API."""

    chain = "TRX"

    async def get_transactions(
        self,
        address: str,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> list[RawTransaction]:
        """Return paginated transactions for a TRX address."""
        url = f"{_BASE_URL}/transaction"
        params: dict = {
            "address": address,
            "limit": page_size,
            "start": (page - 1) * page_size,
        }

        try:
            data = await self._fetch_with_retry(url, params=params)
        except DataUnavailableError:
            logger.warning("TRX: could not fetch transactions for %s", address)
            return []

        items = data.get("data") or []
        if not isinstance(items, list):
            return []

        transactions: list[RawTransaction] = []
        for tx in items:
            try:
                tx_hash = tx.get("hash", "")
                if not tx_hash:
                    continue

                from_addr = tx.get("ownerAddress", "")
                to_addr = tx.get("toAddress", "")

                # amount: contractData.amount in SUN → TRX
                contract_data = tx.get("contractData") or {}
                raw_amount = contract_data.get("amount", 0)
                amount = Decimal(str(raw_amount)) / _SUN_PER_TRX

                # fee in SUN → TRX
                raw_fee = tx.get("cost", {}).get("fee", 0)
                fee = Decimal(str(raw_fee)) / _SUN_PER_TRX

                # timestamp in milliseconds
                raw_ts = tx.get("timestamp", 0)
                timestamp = datetime.fromtimestamp(int(raw_ts) / 1000, tz=timezone.utc)

                block_height_raw = tx.get("block")
                block_height: int | None = int(block_height_raw) if block_height_raw is not None else None

                transactions.append(
                    RawTransaction(
                        tx_hash=tx_hash,
                        from_addr=from_addr,
                        to_addr=to_addr,
                        amount=amount,
                        fee=fee,
                        timestamp=timestamp,
                        chain=self.chain,
                        block_height=block_height,
                    )
                )
            except Exception:  # noqa: BLE001
                logger.debug(
                    "TRX: failed to parse tx %s", tx.get("hash", "<unknown>"), exc_info=True
                )
                continue

        return transactions

    async def get_address_info(self, address: str) -> AddressInfo:
        """Return summary info for a TRX address."""
        url = f"{_BASE_URL}/account"
        params = {"address": address}
        data = await self._fetch_with_retry(url, params=params)

        # balance is in SUN
        raw_balance = data.get("balance", 0)
        balance = Decimal(str(raw_balance)) / _SUN_PER_TRX
        tx_count = data.get("totalTransactionCount", 0)

        return AddressInfo(
            address=address,
            chain=self.chain,
            balance=balance,
            tx_count=tx_count,
            first_seen=None,
            last_seen=None,
        )
