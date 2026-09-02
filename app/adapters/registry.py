"""Adapter registry — maps chain identifiers to BlockchainAdapter classes.

The registry is populated at adapter module import time (see each concrete
adapter module).  At runtime, call :func:`get_adapter` to obtain a ready-to-use
adapter instance for a given chain.

Usage (explicit registration)::

    from app.adapters.registry import register_adapter, get_adapter

    register_adapter("ETH", EtherscanAdapter)
    adapter = get_adapter("ETH")
    txs = await adapter.get_transactions("0xAbC...")

Usage (decorator)::

    from app.adapters.registry import register_adapter

    @register_adapter
    class EtherscanAdapter(BlockchainAdapter):
        chain = "ETH"
        ...
"""

from __future__ import annotations

from app.adapters.base import BlockchainAdapter

# ---------------------------------------------------------------------------
# Registry storage
# ---------------------------------------------------------------------------

#: Maps chain identifier (e.g. ``"ETH"``) → adapter *class* (not instance).
#: Populated by concrete adapter modules via :func:`register_adapter`.
ADAPTER_REGISTRY: dict[str, type[BlockchainAdapter]] = {}


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------


def register_adapter(
    chain_or_cls: str | type[BlockchainAdapter],
    adapter_cls: type[BlockchainAdapter] | None = None,
) -> type[BlockchainAdapter] | None:
    """Register an adapter class in the global registry.

    Supports two calling conventions:

    **Explicit** (as specified in Requirements 4.2)::

        register_adapter("ETH", EtherscanAdapter)

    **Decorator** (convenience for module-level registration)::

        @register_adapter
        class EtherscanAdapter(BlockchainAdapter):
            chain = "ETH"

    Args:
        chain_or_cls: Either a chain identifier string (explicit call) or an
                      adapter class (decorator call).
        adapter_cls:  The adapter class to register (explicit call only).

    Returns:
        The adapter class when used as a decorator; ``None`` for explicit calls.

    Raises:
        ValueError: If the chain identifier is missing, the class lacks a
                    ``chain`` attribute, or the chain is already registered
                    with a different class.
    """
    # -- Decorator usage: @register_adapter (no parens, class passed directly)
    if isinstance(chain_or_cls, type):
        cls = chain_or_cls
        chain = getattr(cls, "chain", None)
        if not chain:
            raise ValueError(
                f"Adapter class {cls.__name__!r} must declare a non-empty "
                "'chain' class attribute."
            )
        _do_register(chain, cls)
        return cls

    # -- Explicit usage: register_adapter("ETH", EtherscanAdapter)
    chain = chain_or_cls
    if not chain:
        raise ValueError("chain identifier must be a non-empty string.")
    if adapter_cls is None:
        raise ValueError(
            "adapter_cls must be provided when chain is given as a string."
        )
    _do_register(chain, adapter_cls)
    return None


def _do_register(chain: str, adapter_cls: type[BlockchainAdapter]) -> None:
    """Internal helper that writes to ADAPTER_REGISTRY with conflict checking."""
    existing = ADAPTER_REGISTRY.get(chain)
    if existing is not None and existing is not adapter_cls:
        raise ValueError(
            f"Chain {chain!r} is already registered with {existing.__name__!r}. "
            f"Cannot re-register with {adapter_cls.__name__!r}."
        )
    ADAPTER_REGISTRY[chain] = adapter_cls


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def get_adapter(chain: str) -> BlockchainAdapter:
    """Return a fresh instance of the adapter registered for *chain*.

    Args:
        chain: Chain identifier, e.g. ``"BTC"``, ``"ETH"``, ``"TRX"``,
               ``"BSC"``, ``"SOL"``, or ``"MATIC"``.

    Returns:
        A new :class:`~app.adapters.base.BlockchainAdapter` instance.

    Raises:
        ValueError: If no adapter is registered for *chain*.
    """
    adapter_cls = ADAPTER_REGISTRY.get(chain)
    if adapter_cls is None:
        registered = sorted(ADAPTER_REGISTRY.keys())
        raise ValueError(
            f"No adapter registered for chain {chain!r}. "
            f"Registered chains: {registered}"
        )
    return adapter_cls()
