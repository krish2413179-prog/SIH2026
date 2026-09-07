"""Live address feed store for real-time trace progress visualization."""

from __future__ import annotations

import threading
from collections import defaultdict

_live_store: dict[str, list[str]] = defaultdict(list)
_store_lock = threading.Lock()


def record_live_address(trace_id: str, address: str) -> None:
    """Record a real address scanned by the backend trace engine."""
    if not trace_id or not address:
        return
    with _store_lock:
        feed = _live_store[str(trace_id)]
        if address not in feed:
            feed.insert(0, address)
            if len(feed) > 100:
                feed.pop()


def get_live_addresses(trace_id: str, limit: int = 20) -> list[str]:
    """Retrieve the most recently scanned real addresses for a given trace_id."""
    with _store_lock:
        return list(_live_store.get(str(trace_id), []))[:limit]
