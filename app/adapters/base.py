"""Abstract base class and shared types for Blockchain Data Adapters.

Implements the common interface required by Requirements 4.2, 4.4, 4.5.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Raw API response archive (P2-3)
# ---------------------------------------------------------------------------

RAW_ARCHIVE_DIR = Path(os.environ.get("RAW_API_ARCHIVE_DIR", "/tmp/api_archive"))


def _archive_response(chain: str, address: str, action: str, body: bytes) -> str:
    """Write raw API response bytes to disk and return the SHA-256 hex digest.

    The archive is a lightweight audit trail: every successful HTTP response
    from an upstream block-explorer API is written to ``RAW_ARCHIVE_DIR`` as a
    JSON file named::

        {chain}_{address[:12]}_{action}_{timestamp}_{sha[:8]}.json

    Archive failures are silently swallowed — they must never interrupt an
    active investigation trace.

    Args:
        chain:   Chain identifier (e.g. ``"ETH"``).
        address: Queried on-chain address (first 12 chars used in filename).
        action:  API action/endpoint label (e.g. ``"txlist"``).
        body:    Raw response bytes from the upstream API.

    Returns:
        Full SHA-256 hex digest of *body*.
    """
    sha = hashlib.sha256(body).hexdigest()
    try:
        RAW_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        fname = (
            RAW_ARCHIVE_DIR
            / f"{chain}_{address[:12]}_{action}_{ts}_{sha[:8]}.json"
        )
        fname.write_bytes(body)
    except Exception:  # noqa: BLE001
        pass  # archive failure must never break a trace
    return sha


# ---------------------------------------------------------------------------
# Shared data types
# ---------------------------------------------------------------------------


@dataclass
class RawTransaction:
    """A normalised on-chain transaction record returned by every adapter."""

    tx_hash: str
    from_addr: str
    to_addr: str
    amount: Decimal
    fee: Decimal
    timestamp: datetime
    chain: str
    block_height: int | None = None
    is_bridge: bool = False
    bridge_protocol: str | None = None

    def edge_attrs(self) -> dict:
        """Return edge-attribute dict suitable for NetworkX graph construction."""
        return {
            "tx_hash": self.tx_hash,
            "amount": float(self.amount),
            "fee": float(self.fee),
            "timestamp": self.timestamp.isoformat(),
            "chain": self.chain,
            "is_bridge": self.is_bridge,
            "bridge_protocol": self.bridge_protocol,
        }


@dataclass
class AddressInfo:
    """Summary information for a single on-chain address."""

    address: str
    chain: str
    balance: Decimal
    tx_count: int
    first_seen: datetime | None
    last_seen: datetime | None


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class RateLimitError(Exception):
    """Raised when the upstream API responds with a rate-limit status."""


class DataUnavailableError(Exception):
    """Raised when data cannot be retrieved after all retries are exhausted."""


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

# Supported chain identifiers
SUPPORTED_CHAINS = frozenset({"BTC", "ETH", "TRX", "BSC", "SOL", "MATIC"})

# Known valid probe addresses per chain, used by the default health_check.
_PROBE_ADDRESSES: dict[str, str] = {
    "BTC": "1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf",   # Genesis block coinbase
    "ETH": "0x0000000000000000000000000000000000000000",
    "TRX": "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb",
    "BSC": "0x0000000000000000000000000000000000000000",
    "SOL": "11111111111111111111111111111111",
    "MATIC": "0x0000000000000000000000000000000000000000",
}

_RETRY_ATTEMPTS = 5
_BACKOFF_BASE = 1.0   # seconds
_BACKOFF_MAX = 60.0   # seconds


class BlockchainAdapter(ABC):
    """Common interface for all per-chain blockchain data adapters.

    Concrete subclasses must declare a ``chain`` class variable matching one
    of the supported chain identifiers and implement ``get_transactions`` and
    ``get_address_info``.

    The ``_fetch_with_retry`` helper provides shared HTTP + backoff logic so
    that concrete adapters only need to focus on parsing chain-specific
    responses.
    """

    #: Chain identifier — must be one of SUPPORTED_CHAINS.
    chain: str

    # ------------------------------------------------------------------ #
    # Abstract interface                                                   #
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def get_transactions(
        self,
        address: str,
        *,
        page: int = 1,
        page_size: int = 500,
    ) -> list[RawTransaction]:
        """Return a paginated list of transactions for *address*.

        Args:
            address:   On-chain address to query.
            page:      1-based page number.
            page_size: Number of transactions per page (hint to upstream API).

        Returns:
            A (possibly empty) list of :class:`RawTransaction` objects ordered
            by timestamp descending, consistent with most block-explorer APIs.

        Raises:
            RateLimitError:      The upstream API enforces a rate limit.
            DataUnavailableError: Data could not be fetched after all retries.
        """
        ...

    @abstractmethod
    async def get_address_info(self, address: str) -> AddressInfo:
        """Return summary metadata for *address*.

        Args:
            address: On-chain address to query.

        Returns:
            An :class:`AddressInfo` instance.

        Raises:
            RateLimitError:      The upstream API enforces a rate limit.
            DataUnavailableError: Data could not be fetched after all retries.
        """
        ...

    # ------------------------------------------------------------------ #
    # Default health check                                                 #
    # ------------------------------------------------------------------ #

    async def health_check(self) -> bool:
        """Probe the upstream API using a known valid address.

        The default implementation calls :meth:`get_address_info` with a
        well-known probe address for this chain.  Concrete adapters may
        override this if a cheaper probe is available (e.g., a status
        endpoint).

        Returns:
            ``True`` if the upstream is reachable and responsive,
            ``False`` otherwise.
        """
        probe = _PROBE_ADDRESSES.get(self.chain)
        if probe is None:
            logger.warning("No probe address configured for chain %s", self.chain)
            return False
        try:
            await self.get_address_info(probe)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Health check failed for chain %s: %s",
                self.chain,
                exc,
            )
            return False

    # ------------------------------------------------------------------ #
    # Redis cache layer                                                    #
    # ------------------------------------------------------------------ #

    async def get_transactions_cached(
        self,
        address: str,
        *,
        page: int = 1,
        page_size: int = 100,
        redis_client,  # redis.asyncio.Redis
        ttl: int = 1800,
    ) -> tuple[list[RawTransaction], int | None]:
        """Fetch transactions with Redis caching.

        Cache key: ``f"blockchain:{self.chain}:{address}:{page}:{page_size}"``

        Returns:
            A ``(transactions, cache_age_seconds)`` tuple.
            ``cache_age_seconds`` is ``None`` on a cache miss (fresh data
            fetched from the upstream API).
            ``cache_age_seconds`` is a non-negative integer on a cache hit
            (seconds elapsed since the entry was stored).

        Requirements: 4.6, 4.7
        """
        import json

        cache_key = f"blockchain:{self.chain}:{address}:{page}:{page_size}"

        # Try cache first (Requirement 4.6)
        cached = await redis_client.get(cache_key)
        if cached is not None:
            remaining_ttl = await redis_client.ttl(cache_key)
            # remaining_ttl is -1 if no TTL set, -2 if key doesn't exist;
            # treat anything non-positive as age == 0 to stay safe.
            cache_age = max(0, ttl - remaining_ttl) if remaining_ttl >= 0 else 0
            data = json.loads(cached)
            transactions = [_raw_tx_from_dict(d) for d in data]
            return transactions, cache_age  # cache hit → age reported (Req 4.7)

        # Cache miss — fetch fresh data from upstream adapter
        transactions = await self.get_transactions(address, page=page, page_size=page_size)

        # Serialise and store in Redis with the configured TTL (Requirement 4.6)
        serializable = [_raw_tx_to_dict(tx) for tx in transactions]
        await redis_client.setex(cache_key, ttl, json.dumps(serializable).encode())

        return transactions, None  # cache miss → no age (Req 4.7)

    # ------------------------------------------------------------------ #
    # Shared HTTP helper with retry / backoff                              #
    # ------------------------------------------------------------------ #

    async def _fetch_with_retry(
        self,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> dict:
        """Perform a GET request with exponential backoff on transient errors.

        On every successful response the raw bytes are archived to disk via
        :func:`_archive_response` (P2-3).  Archive failures are silently
        swallowed so they never interrupt a live trace.

        Retry policy (Requirements 4.4, 4.5):
        - Up to ``_RETRY_ATTEMPTS`` (5) total attempts.
        - On :class:`RateLimitError`: wait ``min(base * 2^attempt, 60s)``
          before retrying; after 5 rate-limit retries raise
          :class:`RateLimitError`.
        - On any other :mod:`httpx` error or :exc:`asyncio.TimeoutError`:
          retry immediately up to the attempt limit; on final failure raise
          :class:`DataUnavailableError`.

        Args:
            url:     Absolute URL to fetch.
            params:  Optional query-string parameters dict.
            headers: Optional additional HTTP headers dict.

        Returns:
            Parsed JSON response body as a ``dict``.

        Raises:
            RateLimitError:      All 5 retries were consumed by rate-limit
                                 responses (HTTP 429/503).
            DataUnavailableError: All retries exhausted without a successful
                                  response due to non-rate-limit errors.
        """
        params = params or {}
        delay = _BACKOFF_BASE
        last_exc: Exception | None = None

        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(_RETRY_ATTEMPTS):
                try:
                    response = await client.get(url, params=params, headers=headers)

                    # Treat HTTP 429 / 503 as a rate-limit signal so that
                    # concrete adapters do not need to re-implement this path.
                    if response.status_code in (429, 503):
                        raise RateLimitError(
                            f"Rate limit response {response.status_code} from {url}"
                        )

                    if response.status_code != 200:
                        logger.error(
                            "%s HTTP %d from %s params=%s",
                            self.chain,
                            response.status_code,
                            url,
                            str(params)[:200],
                        )

                    response.raise_for_status()

                    # ---- P2-3: archive raw response bytes ----------------
                    # httpx populates response.content (bytes) synchronously
                    # after a completed request — no extra await needed.
                    _raw = response.content
                    if _raw:
                        _archive_response(
                            getattr(self, "chain", "unknown"),
                            str(
                                params.get(
                                    "address",
                                    params.get("account", "unknown"),
                                )
                            ),
                            str(params.get("action", "fetch")),
                            _raw,
                        )
                    # -------------------------------------------------------

                    return response.json()  # type: ignore[no-any-return]

                except RateLimitError as exc:
                    last_exc = exc
                    wait = min(delay, _BACKOFF_MAX)
                    logger.info(
                        "Rate limited on %s (attempt %d/%d); backing off %.1fs",
                        url,
                        attempt + 1,
                        _RETRY_ATTEMPTS,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    delay = min(delay * 2, _BACKOFF_MAX)

                except (httpx.HTTPError, asyncio.TimeoutError) as exc:
                    last_exc = exc
                    logger.warning(
                        "HTTP error on %s (attempt %d/%d): %s",
                        url,
                        attempt + 1,
                        _RETRY_ATTEMPTS,
                        exc,
                    )
                    if attempt == _RETRY_ATTEMPTS - 1:
                        raise DataUnavailableError(
                            f"Failed to fetch {url} after {_RETRY_ATTEMPTS} attempts: {exc}"
                        ) from exc
                    # Brief pause before non-rate-limit retries
                    await asyncio.sleep(min(delay, _BACKOFF_MAX))
                    delay = min(delay * 2, _BACKOFF_MAX)

        # Reached only if all retries were consumed by rate-limit errors
        raise RateLimitError(
            f"Rate limit not resolved for {url} after {_RETRY_ATTEMPTS} attempts: {last_exc}"
        )


# ---------------------------------------------------------------------------
# Cache serialisation helpers
# ---------------------------------------------------------------------------


def _raw_tx_to_dict(tx: RawTransaction) -> dict:
    """Serialize a RawTransaction to a JSON-safe dict for caching."""
    return {
        "tx_hash": tx.tx_hash,
        "from_addr": tx.from_addr,
        "to_addr": tx.to_addr,
        "amount": str(tx.amount),
        "fee": str(tx.fee),
        "timestamp": tx.timestamp.isoformat(),
        "chain": tx.chain,
        "block_height": tx.block_height,
        "is_bridge": tx.is_bridge,
        "bridge_protocol": tx.bridge_protocol,
    }


def _raw_tx_from_dict(d: dict) -> RawTransaction:
    """Deserialize a RawTransaction from a cached dict."""
    from datetime import datetime
    from decimal import Decimal

    return RawTransaction(
        tx_hash=d["tx_hash"],
        from_addr=d["from_addr"],
        to_addr=d["to_addr"],
        amount=Decimal(d["amount"]),
        fee=Decimal(d["fee"]),
        timestamp=datetime.fromisoformat(d["timestamp"]),
        chain=d["chain"],
        block_height=d.get("block_height"),
        is_bridge=d.get("is_bridge", False),
        bridge_protocol=d.get("bridge_protocol"),
    )
