"""Unit tests for app.adapters.base and app.adapters.registry.

Covers:
- RawTransaction dataclass and edge_attrs()
- AddressInfo dataclass
- RateLimitError / DataUnavailableError exceptions
- BlockchainAdapter abstract interface and health_check default
- _fetch_with_retry: success, rate-limit backoff, HTTP errors, exhaustion
- register_adapter and get_adapter registry helpers

Requirements: 4.2, 4.4, 4.5
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.adapters.base import (
    AddressInfo,
    BlockchainAdapter,
    DataUnavailableError,
    RateLimitError,
    RawTransaction,
    _BACKOFF_BASE,
    _BACKOFF_MAX,
    _PROBE_ADDRESSES,
    _RETRY_ATTEMPTS,
)
from app.adapters.registry import (
    ADAPTER_REGISTRY,
    get_adapter,
    register_adapter,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_tx(
    *,
    tx_hash: str = "abc123",
    from_addr: str = "0xAAA",
    to_addr: str = "0xBBB",
    amount: Decimal = Decimal("1.5"),
    fee: Decimal = Decimal("0.001"),
    timestamp: datetime = NOW,
    chain: str = "ETH",
    block_height: int | None = 1000,
    is_bridge: bool = False,
    bridge_protocol: str | None = None,
) -> RawTransaction:
    return RawTransaction(
        tx_hash=tx_hash,
        from_addr=from_addr,
        to_addr=to_addr,
        amount=amount,
        fee=fee,
        timestamp=timestamp,
        chain=chain,
        block_height=block_height,
        is_bridge=is_bridge,
        bridge_protocol=bridge_protocol,
    )


class ConcreteAdapter(BlockchainAdapter):
    """Minimal concrete subclass for testing abstract base methods."""

    chain = "ETH"

    async def get_transactions(self, address, *, page=1, page_size=100):
        return []

    async def get_address_info(self, address):
        return AddressInfo(
            address=address,
            chain=self.chain,
            balance=Decimal("0"),
            tx_count=0,
            first_seen=None,
            last_seen=None,
        )


# ---------------------------------------------------------------------------
# RawTransaction tests
# ---------------------------------------------------------------------------


class TestRawTransaction:
    def test_basic_instantiation(self):
        tx = _make_tx()
        assert tx.tx_hash == "abc123"
        assert tx.from_addr == "0xAAA"
        assert tx.to_addr == "0xBBB"
        assert tx.amount == Decimal("1.5")
        assert tx.fee == Decimal("0.001")
        assert tx.chain == "ETH"
        assert tx.block_height == 1000
        assert tx.is_bridge is False
        assert tx.bridge_protocol is None

    def test_block_height_optional(self):
        tx = _make_tx(block_height=None)
        assert tx.block_height is None

    def test_bridge_fields(self):
        tx = _make_tx(is_bridge=True, bridge_protocol="Wormhole")
        assert tx.is_bridge is True
        assert tx.bridge_protocol == "Wormhole"

    def test_edge_attrs_keys(self):
        tx = _make_tx()
        attrs = tx.edge_attrs()
        expected_keys = {"tx_hash", "amount", "fee", "timestamp", "chain", "is_bridge", "bridge_protocol"}
        assert set(attrs.keys()) == expected_keys

    def test_edge_attrs_converts_decimal_to_float(self):
        tx = _make_tx(amount=Decimal("2.5"), fee=Decimal("0.0021"))
        attrs = tx.edge_attrs()
        assert isinstance(attrs["amount"], float)
        assert attrs["amount"] == pytest.approx(2.5)
        assert isinstance(attrs["fee"], float)
        assert attrs["fee"] == pytest.approx(0.0021)

    def test_edge_attrs_timestamp_is_iso_string(self):
        tx = _make_tx(timestamp=NOW)
        attrs = tx.edge_attrs()
        assert isinstance(attrs["timestamp"], str)
        # Should be parseable as ISO 8601
        parsed = datetime.fromisoformat(attrs["timestamp"])
        assert parsed.year == 2024

    def test_edge_attrs_is_bridge_false_by_default(self):
        tx = _make_tx()
        assert tx.edge_attrs()["is_bridge"] is False

    def test_edge_attrs_bridge_protocol_none_by_default(self):
        tx = _make_tx()
        assert tx.edge_attrs()["bridge_protocol"] is None


# ---------------------------------------------------------------------------
# AddressInfo tests
# ---------------------------------------------------------------------------


class TestAddressInfo:
    def test_basic_instantiation(self):
        info = AddressInfo(
            address="0xAAA",
            chain="ETH",
            balance=Decimal("10.5"),
            tx_count=42,
            first_seen=NOW,
            last_seen=NOW,
        )
        assert info.address == "0xAAA"
        assert info.chain == "ETH"
        assert info.balance == Decimal("10.5")
        assert info.tx_count == 42
        assert info.first_seen == NOW
        assert info.last_seen == NOW

    def test_optional_timestamps_can_be_none(self):
        info = AddressInfo(
            address="0xBBB",
            chain="ETH",
            balance=Decimal("0"),
            tx_count=0,
            first_seen=None,
            last_seen=None,
        )
        assert info.first_seen is None
        assert info.last_seen is None


# ---------------------------------------------------------------------------
# Exception tests
# ---------------------------------------------------------------------------


class TestExceptions:
    def test_rate_limit_error_is_exception(self):
        exc = RateLimitError("hit limit on https://example.com")
        assert isinstance(exc, Exception)
        assert "hit limit" in str(exc)

    def test_data_unavailable_error_is_exception(self):
        exc = DataUnavailableError("https://example.com/api")
        assert isinstance(exc, Exception)
        assert "https://example.com/api" in str(exc)

    def test_both_are_distinct_types(self):
        assert RateLimitError is not DataUnavailableError
        assert not issubclass(RateLimitError, DataUnavailableError)
        assert not issubclass(DataUnavailableError, RateLimitError)


# ---------------------------------------------------------------------------
# BlockchainAdapter abstract class tests
# ---------------------------------------------------------------------------


class TestBlockchainAdapterAbstract:
    def test_cannot_instantiate_abstract_class(self):
        with pytest.raises(TypeError):
            BlockchainAdapter()  # type: ignore[abstract]

    def test_concrete_subclass_instantiates(self):
        adapter = ConcreteAdapter()
        assert adapter.chain == "ETH"

    def test_subclass_without_get_transactions_is_abstract(self):
        class IncompleteAdapter(BlockchainAdapter):
            chain = "BTC"

            async def get_address_info(self, address):
                ...  # pragma: no cover

        with pytest.raises(TypeError):
            IncompleteAdapter()  # type: ignore[abstract]

    def test_subclass_without_get_address_info_is_abstract(self):
        class IncompleteAdapter(BlockchainAdapter):
            chain = "BTC"

            async def get_transactions(self, address, *, page=1, page_size=100):
                ...  # pragma: no cover

        with pytest.raises(TypeError):
            IncompleteAdapter()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# health_check default implementation tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_true_on_success(self):
        adapter = ConcreteAdapter()
        result = await adapter.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_exception(self):
        class FailingAdapter(BlockchainAdapter):
            chain = "ETH"

            async def get_transactions(self, address, *, page=1, page_size=100):
                return []

            async def get_address_info(self, address):
                raise DataUnavailableError("network down")

        adapter = FailingAdapter()
        result = await adapter.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_uses_known_probe_address(self):
        """health_check passes the chain-specific sentinel to get_address_info."""
        received_address: list[str] = []

        class CapturingAdapter(BlockchainAdapter):
            chain = "BTC"

            async def get_transactions(self, address, *, page=1, page_size=100):
                return []

            async def get_address_info(self, address):
                received_address.append(address)
                return AddressInfo(
                    address=address,
                    chain=self.chain,
                    balance=Decimal("0"),
                    tx_count=0,
                    first_seen=None,
                    last_seen=None,
                )

        adapter = CapturingAdapter()
        await adapter.health_check()
        assert received_address == [_PROBE_ADDRESSES["BTC"]]

    @pytest.mark.asyncio
    async def test_health_check_returns_false_for_unknown_chain(self):
        class UnknownChainAdapter(BlockchainAdapter):
            chain = "UNKNOWN"

            async def get_transactions(self, address, *, page=1, page_size=100):
                return []

            async def get_address_info(self, address):
                return AddressInfo(
                    address=address,
                    chain=self.chain,
                    balance=Decimal("0"),
                    tx_count=0,
                    first_seen=None,
                    last_seen=None,
                )

        adapter = UnknownChainAdapter()
        result = await adapter.health_check()
        assert result is False


# ---------------------------------------------------------------------------
# _fetch_with_retry tests
#
# Uses httpx.MockTransport to intercept HTTP calls without an external
# mocking library.  Each test injects a custom transport into the
# AsyncClient via patch so that no real network calls are made.
# ---------------------------------------------------------------------------


def _make_transport(*responses: httpx.Response | Exception) -> httpx.AsyncMockTransport:
    """Build an httpx async mock transport that returns responses in order."""
    return httpx.MockTransport(responses)  # type: ignore[attr-defined]


def _response_queue(*items: httpx.Response | Exception) -> httpx.AsyncMockTransport:
    """Return an async transport that pops responses from a list on each call."""
    queue = list(items)

    class _QueueTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    return _QueueTransport()


def _patch_transport(transport: httpx.AsyncBaseTransport):
    """Return a context manager that patches httpx.AsyncClient to use *transport*."""
    return patch(
        "httpx.AsyncClient",
        return_value=httpx.AsyncClient(transport=transport, base_url="https://api.example.com"),
    )


class TestFetchWithRetry:
    @pytest.mark.asyncio
    async def test_successful_response_returned_immediately(self):
        """A 200 OK on the first attempt returns the JSON body."""
        transport = _response_queue(httpx.Response(200, json={"result": "ok"}))
        adapter = ConcreteAdapter()
        with _patch_transport(transport):
            result = await adapter._fetch_with_retry("https://api.example.com/data")
        assert result == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_params_do_not_break_request(self):
        """Passing params should not raise errors."""
        transport = _response_queue(httpx.Response(200, json={"ok": True}))
        adapter = ConcreteAdapter()
        with _patch_transport(transport):
            result = await adapter._fetch_with_retry(
                "https://api.example.com/data", params={"page": "1"}
            )
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_headers_do_not_break_request(self):
        """Passing custom headers should not raise errors."""
        transport = _response_queue(httpx.Response(200, json={"ok": True}))
        adapter = ConcreteAdapter()
        with _patch_transport(transport):
            result = await adapter._fetch_with_retry(
                "https://api.example.com/data",
                headers={"X-API-Key": "secret123"},
            )
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_429_triggers_retry_and_succeeds(self):
        """A single 429 then a 200 should succeed on retry."""
        transport = _response_queue(
            httpx.Response(429, json={"error": "rate limited"}),
            httpx.Response(200, json={"result": "ok"}),
        )
        adapter = ConcreteAdapter()
        with _patch_transport(transport):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await adapter._fetch_with_retry("https://api.example.com/data")

        assert result == {"result": "ok"}
        mock_sleep.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rate_limit_backoff_starts_at_base_delay(self):
        """The first rate-limit backoff sleep should be _BACKOFF_BASE seconds."""
        transport = _response_queue(
            httpx.Response(429),
            httpx.Response(200, json={"ok": True}),
        )
        adapter = ConcreteAdapter()
        sleep_calls: list[float] = []

        async def capture_sleep(secs: float) -> None:
            sleep_calls.append(secs)

        with _patch_transport(transport):
            with patch("asyncio.sleep", side_effect=capture_sleep):
                await adapter._fetch_with_retry("https://api.example.com/data")

        assert sleep_calls[0] == pytest.approx(_BACKOFF_BASE)

    @pytest.mark.asyncio
    async def test_rate_limit_backoff_doubles_each_attempt(self):
        """Successive rate-limit sleeps should double, capped at _BACKOFF_MAX."""
        transport = _response_queue(
            httpx.Response(429),
            httpx.Response(429),
            httpx.Response(429),
            httpx.Response(200, json={"done": True}),
        )
        adapter = ConcreteAdapter()
        sleep_calls: list[float] = []

        async def capture_sleep(secs: float) -> None:
            sleep_calls.append(secs)

        with _patch_transport(transport):
            with patch("asyncio.sleep", side_effect=capture_sleep):
                await adapter._fetch_with_retry("https://api.example.com/data")

        # Delays: 1.0, 2.0, 4.0
        assert sleep_calls[0] == pytest.approx(1.0)
        assert sleep_calls[1] == pytest.approx(2.0)
        assert sleep_calls[2] == pytest.approx(4.0)

    @pytest.mark.asyncio
    async def test_backoff_capped_at_max(self):
        """Sleep delay must never exceed _BACKOFF_MAX."""
        transport = _response_queue(
            *([httpx.Response(429)] * 4),
            httpx.Response(200, json={}),
        )
        adapter = ConcreteAdapter()
        sleep_calls: list[float] = []

        async def capture_sleep(secs: float) -> None:
            sleep_calls.append(secs)

        with _patch_transport(transport):
            with patch("asyncio.sleep", side_effect=capture_sleep):
                await adapter._fetch_with_retry("https://api.example.com/data")

        assert all(s <= _BACKOFF_MAX for s in sleep_calls)

    @pytest.mark.asyncio
    async def test_5_rate_limit_responses_raises_rate_limit_error(self):
        """After all 5 retries consumed by 429s, RateLimitError must be raised."""
        transport = _response_queue(*([httpx.Response(429)] * 5))
        adapter = ConcreteAdapter()
        with _patch_transport(transport):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(RateLimitError):
                    await adapter._fetch_with_retry("https://api.example.com/data")

    @pytest.mark.asyncio
    async def test_503_treated_as_rate_limit(self):
        """HTTP 503 should trigger the same rate-limit backoff path as 429."""
        transport = _response_queue(
            httpx.Response(503),
            httpx.Response(200, json={"ok": True}),
        )
        adapter = ConcreteAdapter()
        with _patch_transport(transport):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await adapter._fetch_with_retry("https://api.example.com/data")
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_non_rate_limit_http_error_raises_data_unavailable(self):
        """After 5 non-rate-limit HTTP errors, DataUnavailableError is raised."""
        transport = _response_queue(
            *([httpx.ConnectError("connection refused")] * 5)
        )
        adapter = ConcreteAdapter()
        with _patch_transport(transport):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(DataUnavailableError) as exc_info:
                    await adapter._fetch_with_retry("https://api.example.com/data")

        assert "https://api.example.com/data" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_transient_error_then_success(self):
        """One httpx error then a 200 should succeed."""
        transport = _response_queue(
            httpx.ConnectError("timeout"),
            httpx.Response(200, json={"data": "value"}),
        )
        adapter = ConcreteAdapter()
        with _patch_transport(transport):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await adapter._fetch_with_retry("https://api.example.com/data")
        assert result == {"data": "value"}

    @pytest.mark.asyncio
    async def test_retry_count_is_5(self):
        """Exactly _RETRY_ATTEMPTS calls should be made before giving up."""
        call_count = 0

        class _CountingTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                nonlocal call_count
                call_count += 1
                raise httpx.ConnectError("timeout")

        adapter = ConcreteAdapter()
        with _patch_transport(_CountingTransport()):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(DataUnavailableError):
                    await adapter._fetch_with_retry("https://api.example.com/data")

        assert call_count == _RETRY_ATTEMPTS


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestAdapterRegistry:
    def setup_method(self):
        """Snapshot and clear registry before each test."""
        self._original = dict(ADAPTER_REGISTRY)
        ADAPTER_REGISTRY.clear()

    def teardown_method(self):
        """Restore original registry after each test."""
        ADAPTER_REGISTRY.clear()
        ADAPTER_REGISTRY.update(self._original)

    # -- register_adapter (explicit two-arg form) ---------------------------

    def test_register_explicit_two_args(self):
        register_adapter("ETH", ConcreteAdapter)
        assert ADAPTER_REGISTRY["ETH"] is ConcreteAdapter

    def test_register_explicit_returns_none(self):
        result = register_adapter("ETH", ConcreteAdapter)
        assert result is None

    def test_register_multiple_chains(self):
        class BTCAdapter(BlockchainAdapter):
            chain = "BTC"

            async def get_transactions(self, address, *, page=1, page_size=100):
                return []

            async def get_address_info(self, address):  # pragma: no cover
                ...

        register_adapter("ETH", ConcreteAdapter)
        register_adapter("BTC", BTCAdapter)
        assert ADAPTER_REGISTRY["ETH"] is ConcreteAdapter
        assert ADAPTER_REGISTRY["BTC"] is BTCAdapter

    def test_register_same_class_twice_is_idempotent(self):
        register_adapter("ETH", ConcreteAdapter)
        register_adapter("ETH", ConcreteAdapter)  # no error
        assert ADAPTER_REGISTRY["ETH"] is ConcreteAdapter

    def test_register_different_class_for_same_chain_raises(self):
        class AnotherETHAdapter(BlockchainAdapter):
            chain = "ETH"

            async def get_transactions(self, address, *, page=1, page_size=100):
                return []

            async def get_address_info(self, address):  # pragma: no cover
                ...

        register_adapter("ETH", ConcreteAdapter)
        with pytest.raises(ValueError, match="already registered"):
            register_adapter("ETH", AnotherETHAdapter)

    def test_register_empty_chain_raises(self):
        with pytest.raises(ValueError):
            register_adapter("", ConcreteAdapter)

    def test_register_without_adapter_cls_raises(self):
        with pytest.raises((ValueError, TypeError)):
            register_adapter("ETH")  # type: ignore[call-arg]

    # -- register_adapter (decorator form) ----------------------------------

    def test_register_as_decorator(self):
        @register_adapter
        class DecoratedAdapter(BlockchainAdapter):
            chain = "ETH"

            async def get_transactions(self, address, *, page=1, page_size=100):
                return []

            async def get_address_info(self, address):  # pragma: no cover
                ...

        assert ADAPTER_REGISTRY["ETH"] is DecoratedAdapter

    def test_register_decorator_returns_class(self):
        @register_adapter
        class DecoratedAdapter2(BlockchainAdapter):
            chain = "ETH"

            async def get_transactions(self, address, *, page=1, page_size=100):
                return []

            async def get_address_info(self, address):  # pragma: no cover
                ...

        # The decorator should return the class itself
        assert DecoratedAdapter2 is not None
        assert issubclass(DecoratedAdapter2, BlockchainAdapter)

    def test_register_decorator_missing_chain_raises(self):
        with pytest.raises(ValueError, match="chain"):
            @register_adapter
            class NoChainAdapter(BlockchainAdapter):
                # Intentionally missing chain attribute
                async def get_transactions(self, address, *, page=1, page_size=100):
                    return []

                async def get_address_info(self, address):  # pragma: no cover
                    ...

    # -- get_adapter --------------------------------------------------------

    def test_get_adapter_returns_instance(self):
        register_adapter("ETH", ConcreteAdapter)
        adapter = get_adapter("ETH")
        assert isinstance(adapter, ConcreteAdapter)

    def test_get_adapter_returns_fresh_instance_each_call(self):
        register_adapter("ETH", ConcreteAdapter)
        a1 = get_adapter("ETH")
        a2 = get_adapter("ETH")
        assert a1 is not a2

    def test_get_adapter_unregistered_chain_raises(self):
        with pytest.raises(ValueError, match="No adapter registered"):
            get_adapter("UNKNOWN_CHAIN")

    def test_get_adapter_error_message_lists_registered_chains(self):
        register_adapter("ETH", ConcreteAdapter)
        with pytest.raises(ValueError) as exc_info:
            get_adapter("BTC")
        assert "ETH" in str(exc_info.value)

    def test_get_adapter_chain_is_set_correctly(self):
        register_adapter("ETH", ConcreteAdapter)
        adapter = get_adapter("ETH")
        assert adapter.chain == "ETH"
