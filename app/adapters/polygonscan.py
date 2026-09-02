"""PolygonscanAdapter — MATIC blockchain data adapter using Polygonscan API.

Inherits the Etherscan-compatible implementation and overrides the base URL
and API key source to target the Polygon network.

Requirements: 4.1, 4.2
"""

from __future__ import annotations

from app.adapters.etherscan import EtherscanAdapter
from app.adapters.registry import register_adapter

_BASE_URL = "https://api.etherscan.io/v2/api"


@register_adapter
class PolygonscanAdapter(EtherscanAdapter):
    """Adapter for the Polygon (MATIC) network via Etherscan V2 API."""

    chain = "MATIC"
    _base_url: str = _BASE_URL
    _chain_id: int = 137  # Polygon mainnet

    def _api_key(self) -> str:
        """Return the Polygonscan API key from settings, falling back to Etherscan key."""
        try:
            from app.config import get_settings
            settings = get_settings()
            return settings.polygonscan_api_key or settings.etherscan_api_key
        except Exception:  # noqa: BLE001
            return ""
