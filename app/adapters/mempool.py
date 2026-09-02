"""MempoolAdapter — BTC blockchain data adapter using mempool.space API.

Requirements: 4.1, 4.2
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from app.adapters.base import AddressInfo, BlockchainAdapter, DataUnavailableError, RawTransaction
from app.adapters.registry import register_adapter

logger = logging.getLogger(__name__)

_BASE_URL = "https://mempool.space/api"


@register_adapter
class MempoolAdapter(BlockchainAdapter):
    """Adapter for the Bitcoin network via mempool.space public API."""

    chain = "BTC"

    async def get_transactions(
        self,
        address: str,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> list[RawTransaction]:
        """Return paginated transactions for a BTC address.

        mempool.space does not accept a page_size parameter; pagination is
        done by passing ``page`` (1-based) to the endpoint.
        """
        url = f"{_BASE_URL}/address/{address}/txs"
        # mempool.space uses ?page= (1-based) but only for confirmed txs;
        # the default endpoint returns up to 25; we pass page number.
        params: dict = {}
        if page > 1:
            params["page"] = page

        try:
            data = await self._fetch_with_retry(url, params=params or None)
        except DataUnavailableError:
            logger.warning("BTC: could not fetch transactions for %s", address)
            return []

        if not isinstance(data, list):
            return []

        transactions: list[RawTransaction] = []
        for tx in data:
            try:
                tx_hash = tx.get("txid", "")
                if not tx_hash:
                    continue

                # from_addr: first input's previous-output address
                vin = tx.get("vin") or []
                from_addr = ""
                for inp in vin:
                    prevout = inp.get("prevout") or {}
                    from_addr = prevout.get("scriptpubkey_address", "")
                    if from_addr:
                        break

                # to_addr: first output address
                vout = tx.get("vout") or []
                to_addr = ""
                for out in vout:
                    to_addr = out.get("scriptpubkey_address", "")
                    if to_addr:
                        break

                # amount: first output value in satoshis → BTC
                amount = Decimal(0)
                if vout:
                    raw_value = vout[0].get("value", 0)
                    amount = Decimal(str(raw_value)) / Decimal("1e8")

                # fee in BTC (field is in satoshis)
                raw_fee = tx.get("fee", 0)
                fee = Decimal(str(raw_fee)) / Decimal("1e8")

                # timestamp: use block_time if confirmed, else 0
                status = tx.get("status") or {}
                raw_ts = status.get("block_time", 0)
                if raw_ts:
                    timestamp = datetime.fromtimestamp(int(raw_ts), tz=timezone.utc)
                else:
                    timestamp = datetime.fromtimestamp(0, tz=timezone.utc)

                # block height
                block_height: int | None = status.get("block_height")

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
                logger.debug("BTC: failed to parse tx %s", tx.get("txid", "<unknown>"), exc_info=True)
                continue

        return transactions

    async def get_address_info(self, address: str) -> AddressInfo:
        """Return summary info for a BTC address."""
        url = f"{_BASE_URL}/address/{address}"
        data = await self._fetch_with_retry(url)

        chain_stats = data.get("chain_stats") or {}
        funded = chain_stats.get("funded_txo_sum", 0)
        spent = chain_stats.get("spent_txo_sum", 0)
        balance = Decimal(str(funded - spent)) / Decimal("1e8")
        tx_count = chain_stats.get("tx_count", 0)

        return AddressInfo(
            address=address,
            chain=self.chain,
            balance=balance,
            tx_count=tx_count,
            first_seen=None,
            last_seen=None,
        )
