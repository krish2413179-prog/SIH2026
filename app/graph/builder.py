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
  - max_per_address cap: top-N transactions by amount to prevent fan-out explosion
  - max_frontier_size cap: trim frontier to top-N addresses by cumulative volume
  - vasp_check_fn: optional callback; addresses flagged as VASP are tagged and
    excluded from further traversal (branch-stop)
  - persist_hop_fn: optional async callback invoked at the start of each hop

Requirements: 5.1, 5.2, 5.3, 5.4
"""

from __future__ import annotations

import asyncio
import logging
import time
import warnings
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

import networkx as nx
import numpy as np

if TYPE_CHECKING:
    from app.adapters import BlockchainAdapter

logger = logging.getLogger(__name__)

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
# Warnings
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
    min_nodes: int = 2000,
    deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
    max_per_address: int = 200,
    max_frontier_size: int = 150,
    persist_hop_fn: Optional[Callable[[int], Awaitable[None]]] = None,
    vasp_check_fn: Optional[Callable[[str], bool]] = None,
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
        Default 2000.  Set high so BFS runs to max_hops unless the wallet
        genuinely has fewer counterparties — the deadline and hop limit are
        the real safety valves.
    deadline_seconds:
        Hard wall-clock budget.  Returns early if exceeded.  Default 300 (5 min).
    max_per_address:
        Maximum transactions to process per address per hop, ranked by amount
        descending.  Safety valve against fan-out explosion on exchange hot
        wallets.  Default 200 — high enough not to truncate normal wallets.
    max_frontier_size:
        Maximum addresses in the BFS frontier after each hop, ranked by
        cumulative transaction volume descending.  Default 150.
    persist_hop_fn:
        Optional async callback ``async (hop: int) -> None`` called at the
        **start** of each hop iteration (1-indexed).  Useful for persisting
        partial graph state to the database between hops.
    vasp_check_fn:
        Optional synchronous callback ``(address: str) -> bool``.  When it
        returns ``True`` the node is tagged ``entity_type='exchange'`` and is
        NOT added to the next frontier (branch-stop on VASP hit).

    Returns
    -------
    nx.DiGraph
        Populated directed graph with per-node metrics.
    """
    max_hops = max(1, min(max_hops, MAX_HOPS_HARD_LIMIT))
    deadline = time.monotonic() + deadline_seconds

    G: nx.DiGraph = nx.DiGraph()
    G.add_node(seed_address, chain=chain)

    # frontier is now a dict: addr -> cumulative_volume for volume-ranked trimming.
    # Initialise with seed at volume 0 so the first hop processes it.
    frontier: dict[str, float] = {seed_address: 0.0}
    visited: set[str] = set()

    for hop in range(max_hops):
        unvisited_frontier = {a: v for a, v in frontier.items() if a not in visited}
        if not unvisited_frontier:
            break

        # ── persist_hop_fn callback (1-indexed) ───────────────────────────
        if persist_hop_fn is not None:
            await persist_hop_fn(hop + 1)

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

        # next_frontier accumulates addr -> cumulative_volume for this hop
        next_frontier: dict[str, float] = {}
        nodes_before_hop = G.number_of_nodes()
        api_calls = 0

        for addr in list(unvisited_frontier.keys()):
            # Per-address deadline check so we don't overshoot on a slow API call
            if time.monotonic() >= deadline:
                warnings.warn(
                    f"build_graph: deadline hit mid-hop {hop + 1} while processing {addr[:10]}…",
                    DeadlineWarning,
                    stacklevel=2,
                )
                frontier = {}  # abort outer loop too
                break

            if G.number_of_nodes() >= NODE_COUNT_LIMIT:
                break

            try:
                txs = await adapter.get_transactions(addr)
            except Exception as exc:
                logger.warning("build_graph: adapter fetch failed for %s: %s", addr, exc)
                txs = []
            api_calls += 1

            # ── max_per_address cap: top-N by amount descending ───────────
            if len(txs) > max_per_address:
                txs = sorted(txs, key=lambda tx: float(tx.amount), reverse=True)[:max_per_address]

            for tx in txs:
                s, t = tx.from_addr, tx.to_addr
                if not s or not t:
                    continue

                tx_amount = float(tx.amount)

                if s not in G:
                    G.add_node(s, chain=chain)
                if t not in G:
                    G.add_node(t, chain=chain)

                is_bridge = t in KNOWN_BRIDGE_CONTRACTS
                G.add_edge(
                    s, t,
                    tx_hash=tx.tx_hash,
                    amount=tx_amount,
                    fee=float(tx.fee),
                    timestamp=(
                        tx.timestamp.isoformat()
                        if hasattr(tx.timestamp, "isoformat")
                        else str(tx.timestamp)
                    ),
                    chain=chain,
                    is_bridge=is_bridge,
                    bridge_protocol=tx.bridge_protocol if is_bridge else None,
                )

                # ── VASP branch-stop ──────────────────────────────────────
                if vasp_check_fn is not None and vasp_check_fn(t):
                    G.nodes[t]["entity_type"] = "exchange"
                    # Do NOT add to next_frontier — stop traversal on this branch
                    continue

                # Both endpoints are counterparties to follow.
                # s may be an address that sends TO addr (incoming tx) — we
                # must add it to next_frontier too, otherwise senders that
                # never appear as destinations are silently dropped.
                counterparty = t if s == addr else s
                next_frontier[counterparty] = next_frontier.get(counterparty, 0.0) + tx_amount
                # Also queue the other endpoint if it is genuinely new
                other = s if counterparty == t else t
                if other != addr and other not in visited:
                    next_frontier[other] = next_frontier.get(other, 0.0) + tx_amount

            visited.add(addr)

        # ── max_frontier_size cap: trim to top-N by volume ────────────────
        if len(next_frontier) > max_frontier_size:
            sorted_items = sorted(next_frontier.items(), key=lambda kv: kv[1], reverse=True)
            next_frontier = dict(sorted_items[:max_frontier_size])

        frontier = next_frontier

        # ── Per-hop INFO log ──────────────────────────────────────────────
        new_nodes = G.number_of_nodes() - nodes_before_hop
        logger.info(
            "build_graph hop=%d frontier=%d visited=%d new_nodes=%d api_calls=%d",
            hop + 1,
            len(frontier),
            len(visited),
            new_nodes,
            api_calls,
        )

        # ── min_nodes check — stop early if we have enough ───────────────
        if G.number_of_nodes() >= min_nodes:
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
    max_per_address: int = 200,
    vasp_check_fn: Optional[Callable[[str], bool]] = None,
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
    max_per_address:
        Maximum transactions to process per leaf address, ranked by amount
        descending.  Default 20.
    vasp_check_fn:
        Optional synchronous callback ``(address: str) -> bool``.  When it
        returns ``True`` the node is tagged ``entity_type='exchange'`` and no
        further edges are added for that destination.

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

        # max_per_address cap
        if len(txs) > max_per_address:
            txs = sorted(txs, key=lambda tx: float(tx.amount), reverse=True)[:max_per_address]

        for tx in txs:
            s, t = tx.from_addr, tx.to_addr
            if not s or not t:
                continue
            if s not in G:
                G.add_node(s, chain=chain)
            if t not in G:
                G.add_node(t, chain=chain)

            # VASP branch-stop
            if vasp_check_fn is not None and vasp_check_fn(t):
                G.nodes[t]["entity_type"] = "exchange"
                continue

            if not G.has_edge(s, t):
                is_bridge = t in KNOWN_BRIDGE_CONTRACTS
                G.add_edge(
                    s, t,
                    tx_hash=tx.tx_hash,
                    amount=float(tx.amount),
                    fee=float(tx.fee),
                    timestamp=(
                        tx.timestamp.isoformat()
                        if hasattr(tx.timestamp, "isoformat")
                        else str(tx.timestamp)
                    ),
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

