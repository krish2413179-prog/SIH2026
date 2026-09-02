"""Address clustering heuristics — CIO (Bitcoin) and deposit-address pattern (EVM/TRX/SOL).

Implements:
  - cluster_bitcoin_cio          — Common-Input Ownership heuristic (Req 6.1, 6.2)
  - cluster_deposit_pattern      — Hub-and-spoke deposit address pattern (Req 6.3, 6.4)

Both functions operate on a NetworkX DiGraph built by the trace worker and return
a list of Cluster dataclass objects ready for the attribution pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx


@dataclass
class Cluster:
    """A set of blockchain addresses inferred to share a single owner.

    Attributes:
        addresses: Unique set of raw address strings belonging to this cluster.
        chain:     Blockchain identifier (BTC | ETH | TRX | BSC | SOL | MATIC).
        method:    Heuristic used to form the cluster: "cio" or "deposit_pattern".
    """

    addresses: set[str] = field(default_factory=set)
    chain: str = ""
    method: str = ""  # "cio" or "deposit_pattern"


# ---------------------------------------------------------------------------
# CIO heuristic — Bitcoin
# ---------------------------------------------------------------------------


def cluster_bitcoin_cio(G: nx.DiGraph) -> list[Cluster]:
    """Common-Input Ownership (CIO) heuristic for Bitcoin.

    For each node *n* in the DiGraph, if two or more predecessor nodes (i.e.
    input addresses that co-spend into the same transaction) exist, they must
    all belong to the same wallet.  We build an undirected co-spend graph and
    use networkx connected-component analysis as the Union-Find equivalent.

    Algorithm:
      1. For every node *n* in G, collect ``predecessors = list(G.predecessors(n))``.
      2. If ``len(predecessors) >= 2``, add undirected edges between every pair
         in the co-spend auxiliary graph.
      3. Compute connected components of the auxiliary graph.
      4. Return one Cluster per component that contains ≥ 2 addresses.

    Args:
        G: Directed transaction graph where a directed edge (A → B) means
           address A sent funds to address B in some transaction.

    Returns:
        List of Cluster objects; single-address components are skipped.
    """
    # Build an undirected co-spend auxiliary graph
    co_spend: nx.Graph = nx.Graph()

    for node in G.nodes():
        predecessors = list(G.predecessors(node))
        if len(predecessors) >= 2:
            # Ensure all predecessor nodes appear in the auxiliary graph
            for addr in predecessors:
                co_spend.add_node(addr)
            # Connect every pair — connected components will merge transitive links
            first = predecessors[0]
            for other in predecessors[1:]:
                co_spend.add_edge(first, other)

    clusters: list[Cluster] = []
    for component in nx.connected_components(co_spend):
        if len(component) >= 2:
            clusters.append(
                Cluster(
                    addresses=set(component),
                    chain="BTC",
                    method="cio",
                )
            )

    return clusters


# ---------------------------------------------------------------------------
# Deposit-address pattern — EVM / TRX / SOL
# ---------------------------------------------------------------------------


def cluster_deposit_pattern(G: nx.DiGraph, chain: str) -> list[Cluster]:
    """Deposit address pattern heuristic for EVM/TRX/SOL chains.

    Identifies "hub-and-spoke" patterns: a central address that receives funds
    from ≥ 10 unique sender addresses — the signature of an exchange deposit
    address cluster.

    Algorithm:
      1. For every node *n* with ``G.in_degree(n) >= 10``:
         - Collect all predecessor (sender) addresses.
         - Include *n* itself as the hub address.
         - Emit a Cluster with method ``"deposit_pattern"``.

    Note: A single address may appear in multiple clusters if it feeds into
    more than one hub.  Downstream de-duplication / merging is handled by the
    attribution pipeline.

    Args:
        G:     Directed transaction graph for *chain*.
        chain: Blockchain identifier (ETH | TRX | BSC | SOL | MATIC).

    Returns:
        List of Cluster objects; nodes with in_degree < 10 are skipped.
    """
    clusters: list[Cluster] = []

    for node, in_degree in G.in_degree():
        if in_degree >= 10:
            senders = set(G.predecessors(node))
            addresses = senders | {node}
            clusters.append(
                Cluster(
                    addresses=addresses,
                    chain=chain,
                    method="deposit_pattern",
                )
            )

    return clusters
