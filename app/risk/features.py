"""Feature Engineering Engine for Blockchain Fraud Detection.
Converts a NetworkX transaction graph into a numerical feature vector for ML inference.
"""

from __future__ import annotations
import numpy as np
import networkx as nx
from typing import Any

class FeatureExtractor:
    """Extracts forensic features from a transaction graph.

    These features are designed to capture VASP-like behavior:
    - High velocity of funds (sweep patterns)
    - Specific fan-in/fan-out ratios
    - Temporal patterns of movement
    """

    @staticmethod
    def extract_node_features(G: nx.DiGraph, seed_node: str) -> dict[str, float]:
        """Calculate features for a specific node in the graph."""

        # 1. Local Connectivity (Fingerprint)
        in_degree = G.in_degree(seed_node)
        out_degree = G.out_degree(seed_node)
        fan_in_out_ratio = in_degree / (out_degree + 1)

        # 2. Value Flux
        total_in = sum(d.get("amount", 0) for _, _, d in G.in_edges(seed_node, data=True))
        total_out = sum(d.get("amount", 0) for _, _, d in G.out_edges(seed_node, data=True))
        value_flux = total_in / (total_out + 1e-6)

        # 3. Temporal Velocity (Avg time delta between in and out)
        in_edges = sorted(G.in_edges(seed_node, data=True), key=lambda x: x[2].get("timestamp", 0))
        out_edges = sorted(G.out_edges(seed_node, data=True), key=lambda x: x[2].get("timestamp", 0))

        velocity = 0.0
        if in_edges and out_edges:
            # Simple heuristic: average difference between first in and first out
            t_in = in_edges[0][2].get("timestamp", 0)
            t_out = out_edges[0][2].get("timestamp", 0)
            velocity = abs(t_out - t_in) if t_in and t_out else 1e9

        # 4. Neighborhood Context
        # % of neighbors that are tagged as VASP/Exchange
        neighbors = list(G.neighbors(seed_node))
        if neighbors:
            vasp_neighbors = [n for n in neighbors if G.nodes[n].get("entity_type") == "CEX"]
            vasp_ratio = len(vasp_neighbors) / len(neighbors)
        else:
            vasp_ratio = 0.0

        return {
            "in_degree": float(in_degree),
            "out_degree": float(out_degree),
            "fan_in_out_ratio": float(fan_in_out_ratio),
            "value_flux": float(value_flux),
            "temporal_velocity": float(velocity),
            "vasp_neighbor_ratio": float(vasp_ratio),
            "total_inflow": float(total_in),
            "total_outflow": float(total_out),
        }

    @staticmethod
    def to_vector(features: dict[str, float]) -> list[float]:
        """Convert feature dict to a sorted list (vector) for ML model input."""
        # The order must match the order used during model training
        keys = [
            "in_degree", "out_degree", "fan_in_out_ratio",
            "value_flux", "temporal_velocity", "vasp_neighbor_ratio",
            "total_inflow", "total_outflow"
        ]
        return [features.get(k, 0.0) for k in keys]
