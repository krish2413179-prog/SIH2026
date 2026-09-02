"""EtherscanAdapter — ETH blockchain data adapter using Etherscan API.

Requirements: 4.1, 4.2
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from app.adapters.base import AddressInfo, BlockchainAdapter, DataUnavailableError, RawTransaction
from app.adapters.registry import register_adapter

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.etherscan.io/v2/api"


@register_adapter
class EtherscanAdapter(BlockchainAdapter):
    """Adapter for the Ethereum network via Etherscan public API."""

    chain = "ETH"

    #: Override in subclasses to point at a different Etherscan-compatible API.
    _base_url: str = _BASE_URL

    def _api_key(self) -> str:
        """Return the Etherscan API key from settings (empty string if not set)."""
        try:
            from app.config import get_settings
            return get_settings().etherscan_api_key
        except Exception:  # noqa: BLE001
            return ""

    # Etherscan V2 chain IDs
    _chain_id: int = 1  # ETH mainnet

    async def get_transactions(
        self,
        address: str,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> list[RawTransaction]:
        """Return paginated transactions for an ETH address."""
        params: dict = {
            "chainid": self._chain_id,
            "module": "account",
            "action": "txlist",
            "address": address,
            "page": page,
            "offset": page_size,
            "sort": "desc",
        }
        api_key = self._api_key()
        if api_key:
            params["apikey"] = api_key

        try:
            data = await self._fetch_with_retry(self._base_url, params=params)
        except DataUnavailableError:
            logger.warning("%s: could not fetch transactions for %s", self.chain, address)
            return []

        status = data.get("status", "0")
        if status != "1":
            # status "0" can mean no transactions or an API error
            message = data.get("message", "")
            result = data.get("result", [])
            if message == "No transactions found" or result == []:
                return []
            logger.warning("%s: unexpected API status %s — %s", self.chain, status, message)
            return []

        result = data.get("result") or []
        if not isinstance(result, list):
            return []

        transactions: list[RawTransaction] = []
        for tx in result:
            try:
                tx_hash = tx.get("hash", "")
                if not tx_hash:
                    continue

                from_addr = tx.get("from", "")
                to_addr = tx.get("to", "")

                # value is in wei
                raw_value = tx.get("value", "0")
                amount = Decimal(str(raw_value)) / Decimal("1e18")

                # fee = gasUsed * gasPrice (both in wei)
                gas_used = int(tx.get("gasUsed", 0))
                gas_price = int(tx.get("gasPrice", 0))
                fee = Decimal(str(gas_used * gas_price)) / Decimal("1e18")

                raw_ts = tx.get("timeStamp", "0")
                timestamp = datetime.fromtimestamp(int(raw_ts), tz=timezone.utc)

                block_height_raw = tx.get("blockNumber")
                block_height: int | None = int(block_height_raw) if block_height_raw else None

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
                    "%s: failed to parse tx %s", self.chain, tx.get("hash", "<unknown>"), exc_info=True
                )
                continue

        return transactions

    async def get_address_info(self, address: str) -> AddressInfo:
        """Return summary info for an ETH address."""
        params: dict = {
            "module": "account",
            "action": "balance",
            "address": address,
            "tag": "latest",
        }
        api_key = self._api_key()
        if api_key:
            params["apikey"] = api_key

        data = await self._fetch_with_retry(self._base_url, params=params)
        raw_balance = data.get("result", "0")
        try:
            balance = Decimal(str(raw_balance)) / Decimal("1e18")
        except Exception:  # noqa: BLE001
            balance = Decimal(0)

        return AddressInfo(
            address=address,
            chain=self.chain,
            balance=balance,
            tx_count=0,  # Etherscan balance endpoint does not return tx_count
            first_seen=None,
            last_seen=None,
        )
