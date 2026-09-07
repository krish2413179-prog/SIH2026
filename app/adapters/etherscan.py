"""EtherscanAdapter — ETH blockchain data adapter using Etherscan API.

Fetches both native ETH transactions (txlist) and ERC-20 token transfers
(tokentx), merging and deduplicating by tx_hash so the graph reflects the
full on-chain activity of each address.

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
        try:
            from app.config import get_settings
            return get_settings().etherscan_api_key
        except Exception:  # noqa: BLE001
            return ""

    # Etherscan V2 chain IDs
    _chain_id: int = 1  # ETH mainnet

    # ------------------------------------------------------------------ #
    # Native ETH transactions                                              #
    # ------------------------------------------------------------------ #

    async def get_transactions(
        self,
        address: str,
        *,
        page: int = 1,
        page_size: int = 500,
    ) -> list[RawTransaction]:
        """Return native ETH transactions + ERC-20 token transfers, merged and
        deduped by tx_hash.  Token transfers with the same hash as a native tx
        replace the native record so the token amount (not the ETH value) is used.
        """
        import asyncio
        native = await self._get_native_transactions(address, page=page, page_size=page_size)
        await asyncio.sleep(0.3)
        tokens = await self._get_token_transactions(address, page=page, page_size=page_size)
        await asyncio.sleep(0.3)

        # Merge: build dict keyed by tx_hash; token txs take priority so that
        # contract calls that move ERC-20 tokens show the token amount instead of 0 ETH.
        merged: dict[str, RawTransaction] = {}
        for tx in native:
            merged[tx.tx_hash] = tx
        for tx in tokens:
            existing = merged.get(tx.tx_hash)
            if existing is None or tx.amount > existing.amount:
                merged[tx.tx_hash] = tx

        return list(merged.values())

    async def _get_native_transactions(
        self,
        address: str,
        *,
        page: int = 1,
        page_size: int = 500,
    ) -> list[RawTransaction]:
        """Fetch standard ETH transfers via action=txlist."""
        import asyncio

        params: dict = {
            "chainid": self._chain_id,
            "module":  "account",
            "action":  "txlist",
            "address": address,
            "page":    page,
            "offset":  page_size,
            "sort":    "desc",
        }
        api_key = self._api_key()
        if api_key:
            params["apikey"] = api_key

        data: dict = {}
        for attempt in range(4):
            try:
                data = await self._fetch_with_retry(self._base_url, params=params)
            except DataUnavailableError:
                logger.warning("%s: could not fetch native txs for %s", self.chain, address)
                return []

            res_str = str(data.get("result") or "").lower()
            msg_str = str(data.get("message") or "").lower()
            if data.get("status") == "0" and ("rate limit" in msg_str or "rate limit" in res_str or "max calls" in res_str):
                logger.info("%s native txlist rate-limited for %s; waiting 1.0s (attempt %d/4)...", self.chain, address[:12], attempt + 1)
                await asyncio.sleep(1.0)
                continue
            break

        if data.get("status") != "1":
            msg = data.get("message", "")
            result_preview = str(data.get("result", ""))[:120]
            if msg in ("No transactions found", "") or data.get("result") == [] or result_preview == "[]":
                return []
            logger.warning(
                "%s native txlist FAILED for %s: status=%s message=%s result_preview=%s",
                self.chain, address[:12], data.get("status"), msg, result_preview,
            )
            return []

        result = data.get("result") or []
        if not isinstance(result, list):
            return []

        out: list[RawTransaction] = []
        for tx in result:
            try:
                tx_hash = tx.get("hash", "")
                if not tx_hash:
                    continue
                from_addr = tx.get("from", "")
                to_addr   = tx.get("to",   "")
                if not from_addr or not to_addr:
                    continue
                amount    = Decimal(str(tx.get("value", "0"))) / Decimal("1e18")
                gas_used  = int(tx.get("gasUsed",  0))
                gas_price = int(tx.get("gasPrice", 0))
                fee       = Decimal(str(gas_used * gas_price)) / Decimal("1e18")
                timestamp = datetime.fromtimestamp(int(tx.get("timeStamp", "0")), tz=timezone.utc)
                block_height_raw = tx.get("blockNumber")
                block_height: int | None = int(block_height_raw) if block_height_raw else None
                out.append(RawTransaction(
                    tx_hash=tx_hash, from_addr=from_addr, to_addr=to_addr,
                    amount=amount, fee=fee, timestamp=timestamp,
                    chain=self.chain, block_height=block_height,
                ))
            except Exception:  # noqa: BLE001
                logger.debug("%s: failed to parse native tx %s", self.chain, tx.get("hash", "?"), exc_info=True)
        return out

    # ------------------------------------------------------------------ #
    # ERC-20 token transfers                                               #
    # ------------------------------------------------------------------ #

    async def _get_token_transactions(
        self,
        address: str,
        *,
        page: int = 1,
        page_size: int = 500,
    ) -> list[RawTransaction]:
        """Fetch ERC-20 token transfers via action=tokentx.

        Token amounts are normalised to a human-readable decimal using the
        token's ``tokenDecimal`` field returned by the API.  The tx_hash is
        preserved so these can be correlated / merged with native txs.
        """
        params: dict = {
            "chainid": self._chain_id,
            "module":  "account",
            "action":  "tokentx",
            "address": address,
            "page":    page,
            "offset":  page_size,
            "sort":    "desc",
        }
        api_key = self._api_key()
        if api_key:
            params["apikey"] = api_key

        import asyncio

        data: dict = {}
        for attempt in range(4):
            try:
                data = await self._fetch_with_retry(self._base_url, params=params)
            except DataUnavailableError:
                logger.debug("%s: could not fetch token txs for %s", self.chain, address)
                return []

            res_str = str(data.get("result") or "").lower()
            msg_str = str(data.get("message") or "").lower()
            if data.get("status") == "0" and ("rate limit" in msg_str or "rate limit" in res_str or "max calls" in res_str):
                logger.info("%s tokentx rate-limited for %s; waiting 1.0s (attempt %d/4)...", self.chain, address[:12], attempt + 1)
                await asyncio.sleep(1.0)
                continue
            break

        if data.get("status") != "1":
            msg = data.get("message", "")
            result_preview = str(data.get("result", ""))[:120]
            if msg in ("No transactions found", "No token transfers found", "") or data.get("result") == [] or result_preview == "[]":
                return []
            logger.warning(
                "%s tokentx FAILED for %s: status=%s message=%s result_preview=%s",
                self.chain, address[:12], data.get("status"), msg, result_preview,
            )
            return []

        result = data.get("result") or []
        if not isinstance(result, list):
            return []

        out: list[RawTransaction] = []
        for tx in result:
            try:
                tx_hash   = tx.get("hash", "")
                if not tx_hash:
                    continue
                from_addr = tx.get("from", "")
                to_addr   = tx.get("to",   "")
                if not from_addr or not to_addr:
                    continue

                # Normalise token amount using its decimal places
                raw_value = tx.get("value", "0")
                decimals  = int(tx.get("tokenDecimal", "18") or "18")
                try:
                    amount = Decimal(str(raw_value)) / Decimal(10 ** decimals)
                except Exception:  # noqa: BLE001
                    amount = Decimal(0)

                # Fee is denominated in ETH regardless of token
                gas_used  = int(tx.get("gasUsed",  0))
                gas_price = int(tx.get("gasPrice", 0))
                fee       = Decimal(str(gas_used * gas_price)) / Decimal("1e18")

                timestamp = datetime.fromtimestamp(int(tx.get("timeStamp", "0")), tz=timezone.utc)
                block_height_raw = tx.get("blockNumber")
                block_height: int | None = int(block_height_raw) if block_height_raw else None

                out.append(RawTransaction(
                    tx_hash=tx_hash, from_addr=from_addr, to_addr=to_addr,
                    amount=amount, fee=fee, timestamp=timestamp,
                    chain=self.chain, block_height=block_height,
                ))
            except Exception:  # noqa: BLE001
                logger.debug("%s: failed to parse token tx %s", self.chain, tx.get("hash", "?"), exc_info=True)
        return out

    # ------------------------------------------------------------------ #
    # Address info                                                         #
    # ------------------------------------------------------------------ #

    async def get_address_info(self, address: str) -> AddressInfo:
        """Return summary info for an ETH address."""
        params: dict = {
            "module":  "account",
            "action":  "balance",
            "address": address,
            "tag":     "latest",
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
            address=address, chain=self.chain, balance=balance,
            tx_count=0, first_seen=None, last_seen=None,
        )
