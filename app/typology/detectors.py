"""Typology detectors for money laundering pattern recognition.

Each detector implements the TypologyDetector protocol and returns a
DetectionResult when the pattern is found, or None otherwise.

Covers Requirements: 9.1, 9.2, 9.3
"""

from __future__ import annotations

import networkx as nx
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class DetectionResult:
    typology: str
    match_confidence: float  # 0.0–1.0
    sub_graph: nx.DiGraph | None = None


@runtime_checkable
class TypologyDetector(Protocol):
    typology_name: str

    def detect(self, G: nx.DiGraph, address: str) -> DetectionResult | None:
        ...


class LayeringDetector:
    """Detects layering: a long simple path with no address reuse.

    Layering is the second stage of money laundering where funds are moved
    through multiple hops to obscure the audit trail.
    """

    typology_name = "layering"

    def detect(self, G: nx.DiGraph, address: str) -> DetectionResult | None:
        try:
            if address not in G:
                return None

            longest_path: list[str] = []
            # Search all simple paths starting from address up to depth 20
            for target in G.nodes:
                if target == address:
                    continue
                try:
                    for path in nx.all_simple_paths(G, address, target, cutoff=20):
                        if len(path) > len(longest_path):
                            longest_path = path
                except (nx.NetworkXError, nx.NodeNotFound):
                    continue

            path_len = len(longest_path)
            # path length is number of nodes; edges = path_len - 1
            # "length > 4" means more than 4 edges, i.e. >= 6 nodes
            if path_len <= 5:
                return None

            # No address reuse — all nodes must be unique (guaranteed by simple path, but verify)
            if len(set(longest_path)) != path_len:
                return None

            confidence = min(0.6 + (path_len - 5) * 0.05, 1.0)

            sub_g = G.subgraph(longest_path).copy()
            return DetectionResult(
                typology=self.typology_name,
                match_confidence=confidence,
                sub_graph=sub_g,
            )
        except (KeyError, AttributeError):
            return None


class PeelChainDetector:
    """Detects peel chains: a linear sequence of hops with diminishing amounts.

    In a peel chain, funds are progressively "peeled off" at each hop —
    each transfer is <= 80% of the previous one.
    """

    typology_name = "peel_chain"

    def detect(self, G: nx.DiGraph, address: str) -> DetectionResult | None:
        try:
            if address not in G:
                return None

            chain = [address]
            current = address

            while True:
                successors = list(G.successors(current))
                # Linear chain: current node must have exactly one out-neighbor
                if len(successors) != 1:
                    break
                nxt = successors[0]
                # Next node must have in_degree=1 and out_degree=1 (strict linear)
                if G.in_degree(nxt) != 1 or G.out_degree(nxt) != 1:
                    break
                # Avoid cycles
                if nxt in chain:
                    break
                chain.append(nxt)
                current = nxt

            if len(chain) < 5:
                return None

            # Check diminishing value: each hop's amount <= 80% of previous
            diminishing = True
            for i in range(1, len(chain)):
                prev_node = chain[i - 1]
                curr_node = chain[i]
                edge_data = G.get_edge_data(prev_node, curr_node) or {}
                prev_edge_data = (
                    G.get_edge_data(chain[i - 2], prev_node) if i >= 2 else None
                )
                curr_amount = edge_data.get("amount")
                prev_amount = (
                    (prev_edge_data or {}).get("amount") if prev_edge_data else None
                )
                if curr_amount is not None and prev_amount is not None:
                    try:
                        if float(curr_amount) > float(prev_amount) * 0.80:
                            diminishing = False
                            break
                    except (TypeError, ValueError):
                        pass

            if not diminishing:
                return None

            sub_g = G.subgraph(chain).copy()
            return DetectionResult(
                typology=self.typology_name,
                match_confidence=0.75,
                sub_graph=sub_g,
            )
        except (KeyError, AttributeError):
            return None


class MixerTumblerDetector:
    """Detects mixer/tumbler activity: high fan-out with uniform output amounts.

    Mixers send to many addresses with nearly identical amounts (within 2%)
    to obscure the origin of funds.
    """

    typology_name = "mixer"

    def detect(self, G: nx.DiGraph, address: str) -> DetectionResult | None:
        try:
            if address not in G:
                return None

            successors = list(G.successors(address))
            fan_out = len(successors)

            if fan_out < 10:
                return None

            # Collect output amounts
            amounts: list[float] = []
            for succ in successors:
                edge_data = G.get_edge_data(address, succ) or {}
                amt = edge_data.get("amount")
                if amt is not None:
                    try:
                        amounts.append(float(amt))
                    except (TypeError, ValueError):
                        pass

            # Check all amounts are within 2% of each other
            if len(amounts) >= 2:
                max_amt = max(amounts)
                min_amt = min(amounts)
                if max_amt > 0 and (max_amt - min_amt) / max_amt > 0.02:
                    return None

            confidence = min(0.6 + fan_out * 0.02, 1.0)

            nodes = {address} | set(successors)
            sub_g = G.subgraph(nodes).copy()
            return DetectionResult(
                typology=self.typology_name,
                match_confidence=confidence,
                sub_graph=sub_g,
            )
        except (KeyError, AttributeError):
            return None


class BridgeAbuseDetector:
    """Detects bridge abuse: use of cross-chain bridge contracts.

    Transactions flagged with is_bridge=True on outgoing edges indicate
    an attempt to move funds across chains to break traceability.
    """

    typology_name = "bridge_abuse"

    def detect(self, G: nx.DiGraph, address: str) -> DetectionResult | None:
        try:
            if address not in G:
                return None

            for _, successor, data in G.out_edges(address, data=True):
                if data.get("is_bridge") is True:
                    sub_g = G.subgraph({address, successor}).copy()
                    return DetectionResult(
                        typology=self.typology_name,
                        match_confidence=0.85,
                        sub_graph=sub_g,
                    )
            return None
        except (KeyError, AttributeError):
            return None


class DarknetDetector:
    """Detects darknet marketplace activity: high in-degree from many unique senders.

    Darknet markets receive payments from many distinct buyers,
    resulting in a high in-degree in the transaction graph.
    """

    typology_name = "darknet"

    def detect(self, G: nx.DiGraph, address: str) -> DetectionResult | None:
        try:
            if address not in G:
                return None

            in_deg = G.in_degree(address)
            if in_deg < 20:
                return None

            confidence = min(0.6 + in_deg * 0.01, 0.95)

            predecessors = list(G.predecessors(address))
            nodes = {address} | set(predecessors)
            sub_g = G.subgraph(nodes).copy()
            return DetectionResult(
                typology=self.typology_name,
                match_confidence=confidence,
                sub_graph=sub_g,
            )
        except (KeyError, AttributeError):
            return None


class RansomwareDetector:
    """Detects ransomware payment aggregation patterns.

    Ransomware wallets collect many small victim payments (high in-degree)
    and consolidate them into few large outputs (low out-degree).
    """

    typology_name = "ransomware"

    def detect(self, G: nx.DiGraph, address: str) -> DetectionResult | None:
        try:
            if address not in G:
                return None

            in_deg = G.in_degree(address)
            out_deg = G.out_degree(address)

            # Many small inputs consolidating to few large outputs
            if in_deg >= 10 and out_deg <= 2:
                predecessors = list(G.predecessors(address))
                successors = list(G.successors(address))
                nodes = {address} | set(predecessors) | set(successors)
                sub_g = G.subgraph(nodes).copy()
                return DetectionResult(
                    typology=self.typology_name,
                    match_confidence=0.70,
                    sub_graph=sub_g,
                )
            return None
        except (KeyError, AttributeError):
            return None


class FraudAggregationDetector:
    """Detects fraud aggregation hubs: addresses receiving from many unique senders.

    Fraud aggregation hubs collect proceeds from many victims (e.g. scams,
    investment fraud) before moving funds onward.
    """

    typology_name = "fraud_aggregation"

    def detect(self, G: nx.DiGraph, address: str) -> DetectionResult | None:
        try:
            if address not in G:
                return None

            in_deg = G.in_degree(address)
            if in_deg < 50:
                return None

            confidence = min(0.7 + in_deg * 0.005, 1.0)

            predecessors = list(G.predecessors(address))
            nodes = {address} | set(predecessors)
            sub_g = G.subgraph(nodes).copy()
            return DetectionResult(
                typology=self.typology_name,
                match_confidence=confidence,
                sub_graph=sub_g,
            )
        except (KeyError, AttributeError):
            return None
