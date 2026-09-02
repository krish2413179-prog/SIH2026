"""Per-chain address format validators for all Supported Chains.

Implements regex + length validation for:
  BTC  — P2PKH (1…), P2SH (3…), bech32 (bc1…)
  ETH  — EVM hex 0x + 40 hex chars
  TRX  — Base58 starting with 'T', 34 chars
  BSC  — Same EVM regex as ETH (EVM-compatible)
  SOL  — Base58, 32–44 chars
  MATIC — Same EVM regex as ETH

Requirements: 3.2, 3.3
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_CHAINS: list[str] = ["BTC", "ETH", "TRX", "BSC", "SOL", "MATIC"]

# Base58 character set (no 0, O, I, l)
_BASE58_CHARS = r"[1-9A-HJ-NP-Za-km-z]"

# ---------------------------------------------------------------------------
# Chain-specific regex patterns
# ---------------------------------------------------------------------------

# Bitcoin
# P2PKH  — starts with '1', 25–34 chars total
_BTC_P2PKH = re.compile(r"^1" + _BASE58_CHARS + r"{24,33}$")
# P2SH   — starts with '3', exactly 34 chars total
_BTC_P2SH = re.compile(r"^3" + _BASE58_CHARS + r"{33}$")
# bech32 — starts with 'bc1', 39–62 chars total (lowercase only per BIP-0173)
_BTC_BECH32 = re.compile(r"^bc1[qpzry9x8gf2tvdw0s3jn54khce6mua7l]{6,87}$")

# EVM-compatible (ETH, BSC, MATIC)
# 0x followed by exactly 40 hexadecimal characters — total 42 chars
_EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")

# Tron
# Base58, starts with 'T', exactly 34 chars total
_TRX_ADDRESS = re.compile(r"^T" + _BASE58_CHARS + r"{33}$")

# Solana
# Base58, 32–44 chars total
_SOL_ADDRESS = re.compile(r"^" + _BASE58_CHARS + r"{32,44}$")


# ---------------------------------------------------------------------------
# Per-chain validator functions
# ---------------------------------------------------------------------------


def validate_btc_address(address: str) -> bool:
    """Return True if *address* is a valid Bitcoin address.

    Accepted formats:
      - P2PKH  : starts with '1', 25–34 chars (Base58)
      - P2SH   : starts with '3', 34 chars (Base58)
      - bech32 : starts with 'bc1', 39–62 chars (lowercase bech32)

    Requirements: 3.2
    """
    if not isinstance(address, str):
        return False
    return bool(
        _BTC_P2PKH.match(address)
        or _BTC_P2SH.match(address)
        or _BTC_BECH32.match(address)
    )


def validate_eth_address(address: str) -> bool:
    """Return True if *address* is a valid Ethereum address.

    Accepts EIP-55 mixed-case, all-lower, or all-upper hex.
    Format: '0x' prefix + 40 hexadecimal characters = 42 chars total.

    Requirements: 3.2
    """
    if not isinstance(address, str):
        return False
    return bool(_EVM_ADDRESS.match(address))


def validate_trx_address(address: str) -> bool:
    """Return True if *address* is a valid Tron address.

    Format: Base58 string starting with 'T', exactly 34 chars total.

    Requirements: 3.2
    """
    if not isinstance(address, str):
        return False
    return bool(_TRX_ADDRESS.match(address))


def validate_bsc_address(address: str) -> bool:
    """Return True if *address* is a valid BNB Chain (BSC) address.

    BSC is EVM-compatible — same format as Ethereum.

    Requirements: 3.2
    """
    return validate_eth_address(address)


def validate_sol_address(address: str) -> bool:
    """Return True if *address* is a valid Solana address.

    Format: Base58 string, 32–44 chars total.

    Requirements: 3.2
    """
    if not isinstance(address, str):
        return False
    return bool(_SOL_ADDRESS.match(address))


def validate_matic_address(address: str) -> bool:
    """Return True if *address* is a valid Polygon (MATIC) address.

    Polygon is EVM-compatible — same format as Ethereum.

    Requirements: 3.2
    """
    return validate_eth_address(address)


# ---------------------------------------------------------------------------
# Dispatcher and multi-chain helpers
# ---------------------------------------------------------------------------

# Map chain identifier → validator function
_VALIDATORS: dict[str, object] = {
    "BTC": validate_btc_address,
    "ETH": validate_eth_address,
    "TRX": validate_trx_address,
    "BSC": validate_bsc_address,
    "SOL": validate_sol_address,
    "MATIC": validate_matic_address,
}


def validate_for_chain(address: str, chain: str) -> bool:
    """Validate *address* against the format rules for *chain*.

    Returns False for unknown chain identifiers rather than raising, so
    callers can safely probe each chain without special-casing unknowns.

    Requirements: 3.2
    """
    validator = _VALIDATORS.get(chain.upper() if isinstance(chain, str) else chain)
    if validator is None:
        return False
    return validator(address)  # type: ignore[operator]


def detect_chains(address: str) -> list[str]:
    """Run *address* through every chain validator and return matching chains.

    EVM-compatible chains (ETH, BSC, MATIC) share the same address format,
    so a '0x…' address legitimately matches all three.

    Example::

        >>> detect_chains("0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B")
        ['ETH', 'BSC', 'MATIC']

    Requirements: 3.2, 3.3
    """
    return [
        chain
        for chain in SUPPORTED_CHAINS
        if validate_for_chain(address, chain)
    ]


# ---------------------------------------------------------------------------
# High-level validation entry point
# ---------------------------------------------------------------------------


class AddressValidationError(ValueError):
    """Raised when an address does not match any Supported Chain format.

    Requirements: 3.3 — The Engine SHALL return HTTP 400 when an address
    fails validation for all Supported Chains.
    """

    def __init__(self, address: str) -> None:
        super().__init__(
            f"Address {address!r} does not match the format of any supported chain "
            f"({', '.join(SUPPORTED_CHAINS)})."
        )
        self.address = address


def validate_address(address: str) -> list[str]:
    """Validate *address* and return the list of detected chains.

    Raises:
        AddressValidationError: If the address does not match any chain's format.

    Returns:
        A non-empty list of chain identifiers the address is valid for.

    Requirements: 3.2, 3.3
    """
    detected = detect_chains(address)
    if not detected:
        raise AddressValidationError(address)
    return detected
