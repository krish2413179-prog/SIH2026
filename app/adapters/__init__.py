"""Blockchain data adapters module (Task 7).

Public re-exports for convenience:

    from app.adapters import (
        BlockchainAdapter,
        RawTransaction,
        AddressInfo,
        RateLimitError,
        DataUnavailableError,
        ADAPTER_REGISTRY,
        register_adapter,
        get_adapter,
    )

Importing this module also registers all concrete adapters via their
module-level ``@register_adapter`` decorators.
"""

from app.adapters.base import (
    AddressInfo,
    BlockchainAdapter,
    DataUnavailableError,
    RateLimitError,
    RawTransaction,
)
from app.adapters.registry import ADAPTER_REGISTRY, get_adapter, register_adapter

# Import concrete adapters to trigger their @register_adapter decorators.
# Order: BTC first, then EVM-compatible chains, then others.
from app.adapters.mempool import MempoolAdapter
from app.adapters.etherscan import EtherscanAdapter
from app.adapters.tronscan import TronscanAdapter
from app.adapters.bscscan import BscScanAdapter
from app.adapters.solscan import SolscanAdapter
from app.adapters.polygonscan import PolygonscanAdapter

__all__ = [
    # Base types
    "AddressInfo",
    "BlockchainAdapter",
    "DataUnavailableError",
    "RateLimitError",
    "RawTransaction",
    # Registry
    "ADAPTER_REGISTRY",
    "get_adapter",
    "register_adapter",
    # Concrete adapters
    "MempoolAdapter",
    "EtherscanAdapter",
    "TronscanAdapter",
    "BscScanAdapter",
    "SolscanAdapter",
    "PolygonscanAdapter",
]
