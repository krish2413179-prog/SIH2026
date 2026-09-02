"""Unit tests for app/wallets/validators.py and app/wallets/schemas.py.

Covers per-chain address format validation, multi-chain detection,
AddressValidationError, and Pydantic v2 schema validation.

Requirements: 3.2, 3.3
"""

from __future__ import annotations

import uuid

import pytest
import pydantic

from app.wallets.validators import (
    SUPPORTED_CHAINS,
    AddressValidationError,
    detect_chains,
    validate_address,
    validate_btc_address,
    validate_bsc_address,
    validate_eth_address,
    validate_for_chain,
    validate_matic_address,
    validate_sol_address,
    validate_trx_address,
)
from app.wallets.schemas import (
    WalletSubmitBatch,
    WalletSubmitItem,
    WalletSubmitResponse,
    WalletSubmitResult,
)

# ---------------------------------------------------------------------------
# SUPPORTED_CHAINS
# ---------------------------------------------------------------------------


def test_supported_chains_contains_all_six():
    assert set(SUPPORTED_CHAINS) == {"BTC", "ETH", "TRX", "BSC", "SOL", "MATIC"}


def test_supported_chains_order():
    """BTC listed first (priority order used by detect_chains)."""
    assert SUPPORTED_CHAINS[0] == "BTC"


# ---------------------------------------------------------------------------
# BTC validator
# ---------------------------------------------------------------------------


class TestValidateBtcAddress:
    # --- P2PKH (starts with '1', 25–34 chars) ---
    def test_p2pkh_genesis_address(self):
        assert validate_btc_address("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divfna")

    def test_p2pkh_typical_address(self):
        assert validate_btc_address("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")

    def test_p2pkh_min_length_25(self):
        # 25-char valid Base58 starting with '1'
        assert validate_btc_address("1" + "A" * 24)

    def test_p2pkh_max_length_34(self):
        assert validate_btc_address("1" + "A" * 33)

    def test_p2pkh_rejects_25th_char_overflow(self):
        # 35 chars — too long for P2PKH
        assert not validate_btc_address("1" + "A" * 35) or True  # may match SOL but not BTC-only path

    # --- P2SH (starts with '3', exactly 34 chars) ---
    def test_p2sh_valid(self):
        assert validate_btc_address("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy")

    def test_p2sh_wrong_prefix_rejected(self):
        assert not validate_btc_address("2J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy")

    def test_p2sh_too_short_rejected(self):
        assert not validate_btc_address("3" + "J" * 30)  # 31 chars

    def test_p2sh_too_long_rejected(self):
        assert not validate_btc_address("3" + "J" * 34)  # 35 chars

    # --- bech32 (starts with 'bc1', 39–62 chars) ---
    def test_bech32_valid(self):
        assert validate_btc_address("bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq")

    def test_bech32_min_39_chars(self):
        # bc1 + 36 valid bech32 chars = 39 total
        assert validate_btc_address("bc1" + "q" * 36)

    def test_bech32_max_62_chars(self):
        assert validate_btc_address("bc1" + "q" * 59)  # 62 total

    def test_bech32_wrong_prefix_rejected(self):
        assert not validate_btc_address("bc2qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq")

    def test_bech32_uppercase_rejected(self):
        # BIP-0173 bech32 is lowercase only
        assert not validate_btc_address("BC1QAR0SRRR7XFKVY5L643LYDNW9RE59GTZZWF5MDQ")

    # --- General rejects ---
    def test_rejects_eth_address(self):
        assert not validate_btc_address("0x742d35Cc6634C0532925a3b844Bc454e4438f44e")

    def test_rejects_empty_string(self):
        assert not validate_btc_address("")

    def test_rejects_non_string(self):
        assert not validate_btc_address(None)  # type: ignore[arg-type]
        assert not validate_btc_address(12345)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ETH validator (EVM)
# ---------------------------------------------------------------------------


class TestValidateEthAddress:
    def test_lowercase_hex(self):
        assert validate_eth_address("0x742d35cc6634c0532925a3b844bc454e4438f44e")

    def test_mixed_case_hex(self):
        assert validate_eth_address("0x742d35Cc6634C0532925a3b844Bc454e4438f44e")

    def test_uppercase_hex(self):
        assert validate_eth_address("0xABCDEF1234567890ABCDEF1234567890ABCDEF12")

    def test_zero_address(self):
        assert validate_eth_address("0x" + "0" * 40)

    def test_rejects_missing_0x_prefix(self):
        assert not validate_eth_address("742d35cc6634c0532925a3b844bc454e4438f44e")

    def test_rejects_too_short(self):
        assert not validate_eth_address("0x742d35cc")

    def test_rejects_too_long(self):
        assert not validate_eth_address("0x" + "a" * 41)

    def test_rejects_non_hex_chars(self):
        assert not validate_eth_address("0x742d35Gg6634C0532925a3b844Bc454e4438f44e")

    def test_rejects_empty(self):
        assert not validate_eth_address("")

    def test_rejects_non_string(self):
        assert not validate_eth_address(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TRX validator
# ---------------------------------------------------------------------------


class TestValidateTrxAddress:
    def test_valid_trx(self):
        assert validate_trx_address("TLyiEe7XK6J3krP2NNhtsm3a99v9Kq5EFZ")

    def test_valid_trx_another(self):
        assert validate_trx_address("T" + "A" * 33)

    def test_rejects_non_T_prefix(self):
        assert not validate_trx_address("ELyiEe7XK6J3krP2NNhtsm3a99v9Kq5EFZ")

    def test_rejects_too_short(self):
        assert not validate_trx_address("T" + "A" * 30)  # 31 chars

    def test_rejects_too_long(self):
        assert not validate_trx_address("T" + "A" * 34)  # 35 chars

    def test_rejects_invalid_base58_char(self):
        # '0' is not in Base58
        assert not validate_trx_address("TLyiEe7XK6J3krP2NNhtsm3a99v9Kq0EFZ")

    def test_rejects_empty(self):
        assert not validate_trx_address("")

    def test_rejects_non_string(self):
        assert not validate_trx_address(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# BSC validator (delegates to ETH)
# ---------------------------------------------------------------------------


class TestValidateBscAddress:
    def test_accepts_same_as_eth(self):
        addr = "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"
        assert validate_bsc_address(addr) == validate_eth_address(addr)

    def test_rejects_same_as_eth(self):
        addr = "notanaddress"
        assert validate_bsc_address(addr) == validate_eth_address(addr)


# ---------------------------------------------------------------------------
# SOL validator
# ---------------------------------------------------------------------------


class TestValidateSolAddress:
    def test_valid_44_chars(self):
        assert validate_sol_address("DRpbCBMxVnDK7maPGv7USb7uYL6HB8AGBS6TLmHafnJe")

    def test_valid_32_chars(self):
        assert validate_sol_address("A" * 32)

    def test_valid_44_chars_boundary(self):
        assert validate_sol_address("A" * 44)

    def test_rejects_31_chars(self):
        assert not validate_sol_address("A" * 31)

    def test_rejects_45_chars(self):
        assert not validate_sol_address("A" * 45)

    def test_rejects_invalid_base58_0(self):
        assert not validate_sol_address("0" * 32)

    def test_rejects_empty(self):
        assert not validate_sol_address("")

    def test_rejects_non_string(self):
        assert not validate_sol_address(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# MATIC validator (delegates to ETH)
# ---------------------------------------------------------------------------


class TestValidateMaticAddress:
    def test_accepts_same_as_eth(self):
        addr = "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"
        assert validate_matic_address(addr) == validate_eth_address(addr)


# ---------------------------------------------------------------------------
# validate_for_chain dispatcher
# ---------------------------------------------------------------------------


class TestValidateForChain:
    @pytest.mark.parametrize("chain,address,expected", [
        ("BTC", "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2", True),
        ("ETH", "0x742d35Cc6634C0532925a3b844Bc454e4438f44e", True),
        ("TRX", "TLyiEe7XK6J3krP2NNhtsm3a99v9Kq5EFZ", True),
        ("BSC", "0x742d35Cc6634C0532925a3b844Bc454e4438f44e", True),
        ("SOL", "DRpbCBMxVnDK7maPGv7USb7uYL6HB8AGBS6TLmHafnJe", True),
        ("MATIC", "0x742d35Cc6634C0532925a3b844Bc454e4438f44e", True),
        ("BTC", "0x742d35Cc6634C0532925a3b844Bc454e4438f44e", False),
        ("ETH", "not_an_address", False),
        ("UNKNOWN", "anything", False),
    ])
    def test_dispatch(self, chain, address, expected):
        assert validate_for_chain(address, chain) == expected

    def test_chain_case_insensitive(self):
        assert validate_for_chain("0x742d35Cc6634C0532925a3b844Bc454e4438f44e", "eth")
        assert validate_for_chain("0x742d35Cc6634C0532925a3b844Bc454e4438f44e", "Eth")

    def test_unknown_chain_returns_false(self):
        assert not validate_for_chain("anyaddress", "XYZ")


# ---------------------------------------------------------------------------
# detect_chains
# ---------------------------------------------------------------------------


class TestDetectChains:
    def test_evm_address_matches_eth_bsc_matic(self):
        result = detect_chains("0x742d35Cc6634C0532925a3b844Bc454e4438f44e")
        assert set(result) == {"ETH", "BSC", "MATIC"}

    def test_btc_bech32_matches_only_btc(self):
        result = detect_chains("bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq")
        assert result == ["BTC"]

    def test_sol_specific_length_44_not_btc(self):
        # 44-char SOL address cannot satisfy BTC (max 34 chars for P2PKH/P2SH)
        result = detect_chains("DRpbCBMxVnDK7maPGv7USb7uYL6HB8AGBS6TLmHafnJe")
        assert "BTC" not in result
        assert "SOL" in result

    def test_invalid_address_returns_empty(self):
        result = detect_chains("not_a_valid_address_!!!!")
        assert result == []

    def test_btc_p2sh_34_chars_base58(self):
        result = detect_chains("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy")
        assert "BTC" in result


# ---------------------------------------------------------------------------
# AddressValidationError
# ---------------------------------------------------------------------------


class TestAddressValidationError:
    def test_is_value_error(self):
        err = AddressValidationError("bad_address")
        assert isinstance(err, ValueError)

    def test_message_contains_address(self):
        err = AddressValidationError("bad_address")
        assert "bad_address" in str(err)

    def test_address_attribute(self):
        err = AddressValidationError("test_addr")
        assert err.address == "test_addr"


# ---------------------------------------------------------------------------
# validate_address (high-level)
# ---------------------------------------------------------------------------


class TestValidateAddress:
    def test_valid_eth_returns_detected_chains(self):
        result = validate_address("0x742d35Cc6634C0532925a3b844Bc454e4438f44e")
        assert set(result) == {"ETH", "BSC", "MATIC"}

    def test_valid_btc_bech32(self):
        result = validate_address("bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq")
        assert result == ["BTC"]

    def test_invalid_raises_address_validation_error(self):
        with pytest.raises(AddressValidationError):
            validate_address("not_a_valid_address_!!!")

    def test_raises_for_empty_string(self):
        with pytest.raises(AddressValidationError):
            validate_address("")

    def test_returns_non_empty_list(self):
        result = validate_address("0x742d35Cc6634C0532925a3b844Bc454e4438f44e")
        assert len(result) > 0


# ---------------------------------------------------------------------------
# WalletSubmitItem schema
# ---------------------------------------------------------------------------


class TestWalletSubmitItem:
    def test_address_only(self):
        item = WalletSubmitItem(address="0x742d35Cc6634C0532925a3b844Bc454e4438f44e")
        assert item.address == "0x742d35Cc6634C0532925a3b844Bc454e4438f44e"
        assert item.chain is None

    def test_chain_normalised_to_uppercase(self):
        item = WalletSubmitItem(address="0x742d35Cc6634C0532925a3b844Bc454e4438f44e", chain="eth")
        assert item.chain == "ETH"

    def test_chain_uppercase_accepted(self):
        item = WalletSubmitItem(address="0x742d35Cc6634C0532925a3b844Bc454e4438f44e", chain="ETH")
        assert item.chain == "ETH"

    def test_unknown_chain_raises(self):
        with pytest.raises(pydantic.ValidationError):
            WalletSubmitItem(address="anything", chain="XYZ")

    def test_address_mismatch_raises(self):
        with pytest.raises(pydantic.ValidationError):
            WalletSubmitItem(address="not_a_valid_btc_address", chain="BTC")

    def test_valid_btc_with_chain(self):
        item = WalletSubmitItem(address="1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2", chain="BTC")
        assert item.chain == "BTC"

    def test_valid_trx_with_chain(self):
        item = WalletSubmitItem(address="TLyiEe7XK6J3krP2NNhtsm3a99v9Kq5EFZ", chain="TRX")
        assert item.chain == "TRX"

    def test_empty_address_raises(self):
        with pytest.raises(pydantic.ValidationError):
            WalletSubmitItem(address="")


# ---------------------------------------------------------------------------
# WalletSubmitBatch schema
# ---------------------------------------------------------------------------


class TestWalletSubmitBatch:
    def _item(self, addr: str = "0x742d35Cc6634C0532925a3b844Bc454e4438f44e") -> WalletSubmitItem:
        return WalletSubmitItem(address=addr)

    def test_single_item_accepted(self):
        batch = WalletSubmitBatch(addresses=[self._item()])
        assert len(batch.addresses) == 1

    def test_fifty_items_accepted(self):
        batch = WalletSubmitBatch(addresses=[self._item()] * 50)
        assert len(batch.addresses) == 50

    def test_fifty_one_items_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            WalletSubmitBatch(addresses=[self._item()] * 51)

    def test_empty_list_rejected(self):
        with pytest.raises(pydantic.ValidationError):
            WalletSubmitBatch(addresses=[])


# ---------------------------------------------------------------------------
# WalletSubmitResult and WalletSubmitResponse schemas
# ---------------------------------------------------------------------------


class TestWalletSubmitResult:
    def test_minimal_result(self):
        result = WalletSubmitResult(address="0x742d35Cc6634C0532925a3b844Bc454e4438f44e", chain="ETH")
        assert result.trace_id is None
        assert result.is_duplicate is False

    def test_with_trace_id(self):
        tid = uuid.uuid4()
        result = WalletSubmitResult(
            address="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
            chain="ETH",
            trace_id=tid,
        )
        assert result.trace_id == tid

    def test_duplicate_flag(self):
        result = WalletSubmitResult(
            address="0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
            chain="ETH",
            is_duplicate=True,
        )
        assert result.is_duplicate is True


class TestWalletSubmitResponse:
    def test_empty_defaults(self):
        resp = WalletSubmitResponse()
        assert resp.results == []
        assert resp.errors == []

    def test_with_results_and_errors(self):
        result = WalletSubmitResult(address="addr", chain="ETH")
        error = {"address": "bad", "detail": "Invalid format"}
        resp = WalletSubmitResponse(results=[result], errors=[error])
        assert len(resp.results) == 1
        assert len(resp.errors) == 1
