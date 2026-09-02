"""Transaction graph construction using NetworkX DiGraph.

Implements BFS-based multi-hop traversal of blockchain transaction data,
converting raw adapter output into an annotated directed graph with per-node
metrics and cross-chain bridge tagging.

Requirements: 5.1, 5.2, 5.3, 5.4
"""

from __future__ import annotations

import warnings
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import networkx as nx
import numpy as np

if TYPE_CHECKING:
    from app.adapters import BlockchainAdapter

# ---------------------------------------------------------------------------
# Constants / configuration
# ---------------------------------------------------------------------------

#: Hard upper limit on BFS depth regardless of caller-supplied value.
MAX_HOPS_HARD_LIMIT: int = 10

#: Node count threshold that triggers a GraphSizeWarning and stops expansion.
NODE_COUNT_LIMIT: int = 10_000

#: Edge count threshold above which low-value edges are pruned.
EDGE_COUNT_PRUNE_THRESHOLD: int = 50_000

#: Percentile below which edges are removed during pruning.
PRUNE_PERCENTILE: float = 10.0

#: Expandable registry of known bridge contract addresses.
#  Add entries via ``KNOWN_BRIDGE_CONTRACTS.add(address)`` at startup.
KNOWN_BRIDGE_CONTRACTS: set[str] = set()


# ---------------------------------------------------------------------------
# Warning class
# ---------------------------------------------------------------------------


class GraphSizeWarning(UserWarning):
    """Emitted when the graph exceeds NODE_COUNT_LIMIT nodes during traversal."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def build_graph(
    seed_address: str,
    chain: str,
    adapter: "BlockchainAdapter",
    max_hops: int = 5,
) -> nx.DiGraph:
    """Build a directed transaction graph via BFS from *seed_address*.

    Parameters
    ----------
    seed_address:
        The starting wallet address for the traversal.
    chain:
        Blockchain identifier (e.g. ``"ETH"``, ``"BTC"``).
    adapter:
        A :class:`~app.adapters.BlockchainAdapter` instance used to fetch
        transactions for each address encountered during traversal.
    max_hops:
        Maximum BFS depth.  Clamped to
        ``[1, MAX_HOPS_HARD_LIMIT]`` internally (default 5, hard max 10).

    Returns
    -------
    nx.DiGraph
        Fully populated directed graph with node and edge attributes as
        defined in the design document (Section 5).

    Notes
    -----
    Memory guards (Requirements 5.3):

    * **Node guard** — when the graph exceeds 10,000 nodes a
      :class:`GraphSizeWarning` is emitted and BFS expansion stops
      immediately.
    * **Edge guard** — when edges exceed 50,000, edges below the 10th
      percentile of ``amount`` values are pruned before returning.

    After traversal :func:`_compute_node_metrics` is called in-place so
    every node carries the metrics required by Requirement 5.4.
    """
    # Clamp max_hops to the hard limit.
    max_hops = max(1, min(max_hops, MAX_HOPS_HARD_LIMIT))

    G: nx.DiGraph = nx.DiGraph()

    # Seed node must exist in the graph even if it has no transactions.
    G.add_node(seed_address, chain=chain)

    frontier: set[str] = {seed_address}
    visited: set[str] = set()
    size_limit_reached = False

    for _hop in range(max_hops):
        if not frontier:
            break

        next_frontier: set[str] = set()

        for addr in frontier - visited:
            # Memory guard: stop expansion when node count exceeds threshold.
            if G.number_of_nodes() >= NODE_COUNT_LIMIT:
                warnings.warn(
                    f"Graph reached {G.number_of_nodes()} nodes "
                    f"(limit {NODE_COUNT_LIMIT}). Stopping expansion.",
                    GraphSizeWarning,
                    stacklevel=2,
                )
                size_limit_reached = True
                break

            txs = await adapter.get_transactions(addr)

            for tx in txs:
                from_addr: str = tx.from_addr
                to_addr: str = tx.to_addr

                # Ensure nodes carry chain attribute (Req 5.1).
                if from_addr not in G:
                    G.add_node(from_addr, chain=chain)
                if to_addr not in G:
                    G.add_node(to_addr, chain=chain)

                # Edge attributes (Req 5.1, 5.2).
                is_bridge: bool = to_addr in KNOWN_BRIDGE_CONTRACTS
                edge_attrs = {
                    "tx_hash": tx.tx_hash,
                    "amount": tx.amount,
                    "fee": tx.fee,
                    "timestamp": tx.timestamp,
                    "chain": chain,
                    "is_bridge": is_bridge,
                    "bridge_protocol": tx.bridge_protocol if is_bridge else None,
                }

                # Allow multiple parallel edges between the same pair of nodes
                # (different tx_hashes).  NetworkX DiGraph keeps only one edge
                # per (u, v) pair; we use the last write wins for simplicity.
                # If multi-edge support is desired, switch to MultiDiGraph.
                G.add_edge(from_addr, to_addr, **edge_attrs)

                next_frontier.add(to_addr)

            visited.add(addr)

        if size_limit_reached:
            break

        frontier = next_frontier

    # Edge memory guard: prune low-value edges if threshold exceeded (Req 5.3).
    if G.number_of_edges() > EDGE_COUNT_PRUNE_THRESHOLD:
        _prune_low_value_edges(G, percentile=PRUNE_PERCENTILE)

    # Compute per-node metrics (Req 5.4).
    _compute_node_metrics(G)

    return G


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_node_metrics(G: nx.DiGraph) -> None:
    """Compute and attach per-node metrics as node attributes in-place.

    Sets the following attributes on every node in *G*:

    * ``in_degree``    — number of incoming edges (int)
    * ``out_degree``   — number of outgoing edges (int)
    * ``total_inflow`` — sum of ``amount`` values for incoming edges (float)
    * ``total_outflow``— sum of ``amount`` values for outgoing edges (float)
    * ``first_seen``   — earliest ``timestamp`` across incident edges (ISO str)
    * ``last_seen``    — latest  ``timestamp`` across incident edges (ISO str)
    * ``entity_type``  — classification label, default ``"unknown"`` (str)

    Requirements: 5.4
    """
    for node in G.nodes():
        in_edges = list(G.in_edges(node, data=True))
        out_edges = list(G.out_edges(node, data=True))

        # Degree counts.
        in_deg: int = len(in_edges)
        out_deg: int = len(out_edges)

        # Inflow / outflow aggregation — amounts may be Decimal or float.
        total_inflow: float = float(
            sum(
                Decimal(str(data.get("amount", 0)))
                for _, _, data in in_edges
            )
        )
        total_outflow: float = float(
            sum(
                Decimal(str(data.get("amount", 0)))
                for _, _, data in out_edges
            )
        )

        # Timestamp range across all incident edges.
        all_timestamps: list[datetime] = []
        for _, _, data in in_edges + out_edges:
            ts = data.get("timestamp")
            if ts is not None:
                if isinstance(ts, datetime):
                    all_timestamps.append(ts)
                else:
                    # Accept ISO strings as a fallback.
                    try:
                        all_timestamps.append(datetime.fromisoformat(str(ts)))
                    except (ValueError, TypeError):
                        pass

        first_seen: str | None = None
        last_seen: str | None = None
        if all_timestamps:
            first_seen = min(all_timestamps).isoformat()
            last_seen = max(all_timestamps).isoformat()

        # Preserve existing entity_type if already set (e.g. by attribution).
        existing_entity_type: str = G.nodes[node].get("entity_type", "unknown")

        G.nodes[node].update(
            {
                "in_degree": in_deg,
                "out_degree": out_deg,
                "total_inflow": total_inflow,
                "total_outflow": total_outflow,
                "first_seen": first_seen,
                "last_seen": last_seen,
                "entity_type": existing_entity_type,
            }
        )


def _prune_low_value_edges(G: nx.DiGraph, percentile: float = 10.0) -> None:
    """Remove edges below *percentile* of the distribution of edge amounts.

    This is a memory-management step invoked when the graph exceeds
    ``EDGE_COUNT_PRUNE_THRESHOLD`` edges (Req 5.3).  Edges with ``amount``
    attribute missing or zero are treated as zero-value and are candidates for
    pruning.

    Parameters
    ----------
    G:
        The directed graph to prune in-place.
    percentile:
        Edges whose ``amount`` falls below this percentile of all edge amounts
        are removed.  Defaults to ``10.0`` (10th percentile).
    """
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
