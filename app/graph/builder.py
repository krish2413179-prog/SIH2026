"""Transaction graph construction using NetworkX DiGraph.

BFS-based multi-hop traversal with:
  - ERC-20 / token tx support (via adapter.get_transactions which now merges both)
  - min_nodes guarantee: keeps expanding hops until the graph has >= min_nodes
    unique wallet addresses, up to max_hops hard limit
  - deadline_seconds: hard wall-clock timeout — returns whatever was built so far
    if the deadline fires before min_nodes is reached
  - on-demand expand: build_graph_expand() deepens an existing nx.DiGraph by
    one additional BFS hop from all leaf nodes (no incoming edges from inside
    the existing graph)

Requirements: 5.1, 5.2, 5.3, 5.4
"""

from __future__ import annotations

import asyncio
import time
import warnings
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import networkx as nx
import numpy as np

if TYPE_CHECKING:
    from app.adapters import BlockchainAdapter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Hard upper limit on BFS depth regardless of caller-supplied value.
MAX_HOPS_HARD_LIMIT: int = 10

#: Minimum wallets we aim for before stopping BFS.
DEFAULT_MIN_NODES: int = 20

#: Wall-clock budget in seconds for the build phase.
DEFAULT_DEADLINE_SECONDS: float = 300.0  # 5 minutes

#: Stop BFS expansion once the graph exceeds this many nodes.
NODE_COUNT_LIMIT: int = 10_000

#: Prune low-value edges once the graph exceeds this many edges.
EDGE_COUNT_PRUNE_THRESHOLD: int = 50_000

#: Percentile below which edges are pruned.
PRUNE_PERCENTILE: float = 10.0

#: Expandable registry of known bridge contract addresses.
KNOWN_BRIDGE_CONTRACTS: set[str] = set()


# ---------------------------------------------------------------------------
# Warning
# ---------------------------------------------------------------------------


class GraphSizeWarning(UserWarning):
    """Emitted when the graph exceeds NODE_COUNT_LIMIT nodes during traversal."""


class DeadlineWarning(UserWarning):
    """Emitted when build_graph returns early because the deadline was hit."""


class MinNodesWarning(UserWarning):
    """Emitted when build_graph exhausted max_hops without reaching min_nodes."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def build_graph(
    seed_address: str,
    chain: str,
    adapter: "BlockchainAdapter",
    max_hops: int = 5,
    *,
    min_nodes: int = DEFAULT_MIN_NODES,
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
) -> nx.DiGraph:
    """Build a directed transaction graph via BFS from *seed_address*.

    Expansion continues hop-by-hop until **any** of these conditions is met:

    1. ``G.number_of_nodes() >= min_nodes``  — target reached ✓
    2. All BFS frontiers exhausted (no more new addresses to visit)
    3. ``max_hops`` reached (clamped to MAX_HOPS_HARD_LIMIT)
    4. Wall-clock time since the call exceeds ``deadline_seconds``
    5. Node count guard: graph >= NODE_COUNT_LIMIT

    In cases 2-5 the function returns whatever was built up to that point
    and emits an appropriate warning.  It never raises on timeout.

    Parameters
    ----------
    seed_address:
        Starting wallet address.
    chain:
        Blockchain identifier (``"ETH"``, ``"BSC"``, ``"BTC"``, …).
    adapter:
        :class:`~app.adapters.BlockchainAdapter` used to fetch transactions.
        For Etherscan-family chains this now returns both native + ERC-20 txs.
    max_hops:
        Maximum BFS depth (clamped to MAX_HOPS_HARD_LIMIT).
    min_nodes:
        Keep expanding hops until the graph has at least this many nodes.
        Default 20.
    deadline_seconds:
        Hard wall-clock budget.  Returns early if exceeded.  Default 300 (5 min).

    Returns
    -------
    nx.DiGraph
        Populated directed graph with per-node metrics.
    """
    max_hops = max(1, min(max_hops, MAX_HOPS_HARD_LIMIT))
    deadline = time.monotonic() + deadline_seconds

    G: nx.DiGraph = nx.DiGraph()
    G.add_node(seed_address, chain=chain)

    frontier: set[str] = {seed_address}
    visited:  set[str] = set()

    for hop in range(max_hops):
        if not frontier:
            break

        # ── Deadline check ────────────────────────────────────────────────
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            warnings.warn(
                f"build_graph: deadline hit after hop {hop} "
                f"(nodes={G.number_of_nodes()}, target={min_nodes}). "
                "Returning partial graph.",
                DeadlineWarning,
                stacklevel=2,
            )
            break

        # ── Node limit guard ──────────────────────────────────────────────
        if G.number_of_nodes() >= NODE_COUNT_LIMIT:
            warnings.warn(
                f"build_graph: node limit {NODE_COUNT_LIMIT} reached at hop {hop}.",
                GraphSizeWarning,
                stacklevel=2,
            )
            break

        next_frontier: set[str] = set()

        for addr in frontier - visited:
            # Per-address deadline check so we don't overshoot on a slow API call
            if time.monotonic() >= deadline:
                warnings.warn(
                    f"build_graph: deadline hit mid-hop {hop} while processing {addr[:10]}…",
                    DeadlineWarning,
                    stacklevel=2,
                )
                frontier = set()  # abort outer loop too
                break

            if G.number_of_nodes() >= NODE_COUNT_LIMIT:
                break

            txs = await adapter.get_transactions(addr)

            for tx in txs:
                s, t = tx.from_addr, tx.to_addr
                if not s or not t:
                    continue
                if s not in G:
                    G.add_node(s, chain=chain)
                if t not in G:
                    G.add_node(t, chain=chain)

                is_bridge = t in KNOWN_BRIDGE_CONTRACTS
                G.add_edge(s, t,
                    tx_hash=tx.tx_hash,
                    amount=float(tx.amount),
                    fee=float(tx.fee),
                    timestamp=tx.timestamp.isoformat() if hasattr(tx.timestamp, "isoformat") else str(tx.timestamp),
                    chain=chain,
                    is_bridge=is_bridge,
                    bridge_protocol=tx.bridge_protocol if is_bridge else None,
                )
                next_frontier.add(t)

            visited.add(addr)

        frontier = next_frontier

        # ── min_nodes check — stop early if we have enough ────────────────
        n = G.number_of_nodes()
        if n >= min_nodes:
            break

    # ── Post-loop warnings ────────────────────────────────────────────────
    final_n = G.number_of_nodes()
    if final_n < min_nodes and time.monotonic() < deadline:
        warnings.warn(
            f"build_graph: exhausted all hops/frontiers with only {final_n} nodes "
            f"(target {min_nodes}). The wallet may genuinely have few counterparties.",
            MinNodesWarning,
            stacklevel=2,
        )

    # ── Edge pruning ──────────────────────────────────────────────────────
    if G.number_of_edges() > EDGE_COUNT_PRUNE_THRESHOLD:
        _prune_low_value_edges(G, percentile=PRUNE_PERCENTILE)

    # ── Node metrics ──────────────────────────────────────────────────────
    _compute_node_metrics(G)

    return G


async def build_graph_expand(
    G: nx.DiGraph,
    chain: str,
    adapter: "BlockchainAdapter",
    *,
    deadline_seconds: float = 120.0,
) -> nx.DiGraph:
    """Expand an existing graph by one additional BFS hop from leaf nodes.

    Leaf nodes = nodes with ``out_degree == 0`` inside *G* (no outgoing edges
    explored yet).  This lets the UI trigger deeper investigation of a
    completed graph on demand without re-running the full trace.

    Parameters
    ----------
    G:
        Existing graph to expand **in-place**.
    chain, adapter:
        Same chain/adapter as the original trace.
    deadline_seconds:
        Wall-clock budget for this expansion step.  Default 120 s (2 min).

    Returns
    -------
    nx.DiGraph
        The same *G* object, expanded in-place, with metrics recomputed.
    """
    deadline = time.monotonic() + deadline_seconds

    # Leaves: nodes that have no outgoing edges in the current graph
    leaves = {n for n in G.nodes() if G.out_degree(n) == 0}

    if not leaves:
        return G  # nothing to expand

    for addr in leaves:
        if time.monotonic() >= deadline:
            break
        if G.number_of_nodes() >= NODE_COUNT_LIMIT:
            break

        txs = await adapter.get_transactions(addr)
        for tx in txs:
            s, t = tx.from_addr, tx.to_addr
            if not s or not t:
                continue
            if s not in G:
                G.add_node(s, chain=chain)
            if t not in G:
                G.add_node(t, chain=chain)
            if not G.has_edge(s, t):
                is_bridge = t in KNOWN_BRIDGE_CONTRACTS
                G.add_edge(s, t,
                    tx_hash=tx.tx_hash,
                    amount=float(tx.amount),
                    fee=float(tx.fee),
                    timestamp=tx.timestamp.isoformat() if hasattr(tx.timestamp, "isoformat") else str(tx.timestamp),
                    chain=chain,
                    is_bridge=is_bridge,
                    bridge_protocol=tx.bridge_protocol if is_bridge else None,
                )

    if G.number_of_edges() > EDGE_COUNT_PRUNE_THRESHOLD:
        _prune_low_value_edges(G, percentile=PRUNE_PERCENTILE)

    _compute_node_metrics(G)
    return G


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_node_metrics(G: nx.DiGraph) -> None:
    """Annotate every node with degree, flow, and timestamp metrics in-place."""
    for node in G.nodes():
        in_edges  = list(G.in_edges(node,  data=True))
        out_edges = list(G.out_edges(node, data=True))

        total_inflow: float = float(sum(
            Decimal(str(d.get("amount", 0))) for _, _, d in in_edges
        ))
        total_outflow: float = float(sum(
            Decimal(str(d.get("amount", 0))) for _, _, d in out_edges
        ))

        all_timestamps: list[datetime] = []
        for _, _, data in in_edges + out_edges:
            ts = data.get("timestamp")
            if ts is not None:
                if isinstance(ts, datetime):
                    all_timestamps.append(ts)
                else:
                    try:
                        all_timestamps.append(datetime.fromisoformat(str(ts)))
                    except (ValueError, TypeError):
                        pass

        first_seen: str | None = min(all_timestamps).isoformat() if all_timestamps else None
        last_seen:  str | None = max(all_timestamps).isoformat() if all_timestamps else None

        existing_entity_type: str = G.nodes[node].get("entity_type", "unknown")

        G.nodes[node].update({
            "in_degree":     len(in_edges),
            "out_degree":    len(out_edges),
            "total_inflow":  total_inflow,
            "total_outflow": total_outflow,
            "first_seen":    first_seen,
            "last_seen":     last_seen,
            "entity_type":   existing_entity_type,
        })


def _prune_low_value_edges(G: nx.DiGraph, percentile: float = 10.0) -> None:
    """Remove edges below *percentile* of the amount distribution."""
    amounts: list[float] = []
    for _u, _v, data in G.edges(data=True):
        try:
            amounts.append(float(data.get("amount", 0)))
        except (TypeError, ValueError):
            amounts.append(0.0)

    if not amounts:
        return

    threshold: float = float(np.percentile(amounts, percentile))
    edges_to_remove = [
        (u, v)
        for u, v, data in G.edges(data=True)
        if float(data.get("amount", 0)) < threshold
    ]
    G.remove_edges_from(edges_to_remove)
