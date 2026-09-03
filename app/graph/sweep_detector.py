"""Deposit Address Sweep Detection Heuristic.

Centralized crypto exchanges assign unique, temporary deposit addresses to each user.
When a user deposits funds, the exchange automatically sweeps 95-100% of those funds
into a main Exchange Hot Wallet.

This detector analyzes NetworkX transaction graphs to identify unlabeled nodes that
match this sweep pattern, attributing them to the parent exchange.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import networkx as nx

logger = logging.getLogger(__name__)


@dataclass
class SweepResult:
    """Identification result for a detected exchange deposit address."""

    deposit_address: str
    parent_exchange: str
    hot_wallet: str
    sweep_ratio: float       # 0.95 to 1.00
    confidence: float        # 0.85 to 0.95


def detect_deposit_sweeps(
    G: nx.DiGraph,
    known_hot_wallets: set[str] | dict[str, str],
) -> dict[str, SweepResult]:
    """Identify exchange deposit addresses in *G* based on fund sweep behavior.

    Args:
        G: Directed transaction graph built by trace worker.
        known_hot_wallets: Set of known exchange hot wallet addresses OR dict
                           mapping ``hot_wallet_address -> exchange_name``.

    Returns:
        Dict mapping ``deposit_address -> SweepResult``.
    """
    hot_wallet_map: dict[str, str] = {}
    if isinstance(known_hot_wallets, set):
        for addr in known_hot_wallets:
            hot_wallet_map[addr.lower()] = "Known Exchange"
    else:
        for addr, name in known_hot_wallets.items():
            hot_wallet_map[addr.lower()] = name

    results: dict[str, SweepResult] = {}

    for node in G.nodes():
        # Skip if already a known hot wallet
        if node.lower() in hot_wallet_map:
            continue

        out_edges = list(G.out_edges(node, data=True))
        if not out_edges:
            continue

        total_outflow = sum(float(data.get("amount", 0)) for _, _, data in out_edges)
        if total_outflow <= 0:
            continue

        # Group outflows by destination target
        target_outflow: dict[str, float] = {}
        for _, target, data in out_edges:
            amt = float(data.get("amount", 0))
            target_outflow[target] = target_outflow.get(target, 0.0) + amt

        # Find target receiving the largest share of outflow
        best_target = max(target_outflow, key=lambda t: target_outflow[t])
        best_amount = target_outflow[best_target]
        sweep_ratio = best_amount / total_outflow

        # Condition 1: 95%+ of all funds sent from node go to one destination
        if sweep_ratio < 0.95:
            continue

        # Condition 2: destination is a known exchange hot wallet
        best_target_lower = best_target.lower()
        if best_target_lower in hot_wallet_map:
            exchange_name = hot_wallet_map[best_target_lower]
            confidence = min(0.85 + (sweep_ratio - 0.95) * 2.0, 0.95)

            results[node] = SweepResult(
                deposit_address=node,
                parent_exchange=exchange_name,
                hot_wallet=best_target,
                sweep_ratio=round(sweep_ratio, 4),
                confidence=round(confidence, 2),
            )

    logger.info("detect_deposit_sweeps: identified %d exchange deposit addresses", len(results))
    return results
