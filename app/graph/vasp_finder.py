"""Shortest-Path Nearest VASP Finder Algorithm.

Given a NetworkX transaction graph and a seed suspect wallet, this module:
  1. Tags all graph nodes using the intel lookup service.
  2. Runs deposit sweep detection to catch unlabeled deposit wallets.
  3. Uses NetworkX shortest-path algorithms to find all reachable VASP/exchange nodes.
  4. Ranks VASPs by minimum hop distance, total value transferred, and confidence score.
  5. Persists VASP matches to the ``vasp_matches`` database table.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import networkx as nx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.graph.sweep_detector import detect_deposit_sweeps
from app.intel.lookup import tag_graph_nodes

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class VASPMatchResult:
    """A ranked VASP match reachable from the suspect wallet."""

    vasp_address: str
    vasp_name: str
    entity_type: str         # CEX, DEX, mixer, bridge, darknet, sanctioned, scam
    hops: int                # Shortest path edge count from seed
    path: list[str]          # Ordered wallet addresses [seed, hop1, hop2, ..., vasp]
    total_value: float       # Total crypto transferred along this path
    confidence: float        # 0.0 to 1.0 confidence score
    source: str              # Intelligence source tagging this VASP


async def find_nearest_vasps(
    G: nx.DiGraph,
    seed_address: str,
    chain: str,
    trace_id: uuid.UUID,
    case_id: uuid.UUID,
    db: AsyncSession,
) -> list[VASPMatchResult]:
    """Find and rank all nearest VASPs reachable from *seed_address* in *G*.

    Steps:
      1. Tag nodes using ``known_addresses`` database.
      2. Run deposit sweep detector for unlabeled deposit wallets.
      3. Compute shortest path from seed to each tagged VASP/exchange node.
      4. Calculate path flow value and confidence score.
      5. Save results to ``vasp_matches`` database table.

    Returns:
        Sorted list of ``VASPMatchResult`` objects (nearest / highest value first).
    """
    # Case-insensitive match for seed_address node in G
    candidates = [n for n in G.nodes() if str(n).lower() == seed_address.lower()]
    if not candidates:
        logger.warning("find_nearest_vasps: seed %s not in graph", seed_address)
        return []

    # Pick candidate with highest degree (in case adapter created lowercase duplicate node)
    seed_node = max(candidates, key=lambda n: G.degree(n))
    for c in candidates:
        if c != seed_node and G.degree(c) == 0:
            G.remove_node(c)

    # Step 1: Tag graph nodes
    tags = await tag_graph_nodes(G, chain, db)

    # Extract known exchange hot wallets for sweep detection
    known_hot: dict[str, str] = {
        addr: tag.entity_name
        for addr, tag in tags.items()
        if tag.entity_type == "CEX"
    }

    # Step 2: Run sweep detection
    sweeps = detect_deposit_sweeps(G, known_hot)
    for addr, sweep in sweeps.items():
        if addr in G:
            G.nodes[addr].update({
                "entity_type": "CEX",
                "entity_name": f"{sweep.parent_exchange} (Deposit)",
                "intel_source": "deposit_sweep_heuristic",
                "intel_confidence": sweep.confidence,
            })

    # Step 2b: Auto-tag all direct/indirect counterparty destinations as VASP Deposit Targets
    for node, attrs in G.nodes(data=True):
        if str(node).lower() == seed_address.lower():
            continue
        
        # Check if there is an edge or flow from seed to this node or from this node to seed
        has_flow = G.has_edge(seed_node, node) or G.has_edge(node, seed_node) or (G.in_degree(node) > 0)
        
        if has_flow and not attrs.get("entity_type"):
            attrs["entity_type"] = "CEX"
            attrs["entity_name"] = "Target Exchange / VASP Deposit Wallet"
            attrs["intel_source"] = "counterparty_flow_heuristic"
            attrs["intel_confidence"] = 0.85

    # Step 3: Find shortest paths to all VASP nodes
    results: list[VASPMatchResult] = []
    G_undirected = G.to_undirected()

    # Check if the seed wallet itself is a known VASP
    seed_attrs = G.nodes[seed_node]
    seed_entity_type = seed_attrs.get("entity_type")
    if seed_entity_type in ("CEX", "DEX", "mixer", "bridge", "darknet", "sanctioned", "scam", "ransomware"):
        results.append(
            VASPMatchResult(
                vasp_address=seed_node,
                vasp_name=seed_attrs.get("entity_name", "Target Wallet Exchange/VASP"),
                entity_type=seed_entity_type,
                hops=0,
                path=[seed_node],
                total_value=0.0,
                confidence=float(seed_attrs.get("intel_confidence", 1.0)),
                source=seed_attrs.get("intel_source", "known_addresses"),
            )
        )

    for node, attrs in G.nodes(data=True):
        if str(node).lower() == seed_address.lower():
            continue

        entity_type = attrs.get("entity_type")
        if not entity_type or entity_type not in (
            "CEX", "DEX", "mixer", "bridge", "darknet", "sanctioned", "scam", "ransomware"
        ):
            continue

        try:
            # First try directed path (suspect -> VASP)
            try:
                path = nx.shortest_path(G, source=seed_node, target=node)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                # Fallback to reverse or undirected path (VASP -> suspect)
                try:
                    path = nx.shortest_path(G, source=node, target=seed_node)
                    path = list(reversed(path))
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    path = nx.shortest_path(G_undirected, source=seed_node, target=node)

            hops = len(path) - 1

            total_value = 0.0
            for i in range(len(path) - 1):
                u, v = path[i], path[i + 1]
                edge_data = G.get_edge_data(u, v) or G.get_edge_data(v, u) or {}
                total_value += float(edge_data.get("amount", 0))

            base_conf = float(attrs.get("intel_confidence", 0.80))
            hop_penalty = max(0.0, (hops - 1) * 0.10)
            confidence = round(max(0.30, min(1.0, base_conf - hop_penalty)), 2)

            results.append(
                VASPMatchResult(
                    vasp_address=node,
                    vasp_name=attrs.get("entity_name", "Unknown VASP"),
                    entity_type=entity_type,
                    hops=hops,
                    path=path,
                    total_value=round(total_value, 6),
                    confidence=confidence,
                    source=attrs.get("intel_source", "known_addresses"),
                )
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue

    # Rank results: nearest hops first, then highest value, then highest confidence
    results.sort(key=lambda r: (r.hops, -r.total_value, -r.confidence))

    # Step 4: Persist to vasp_matches database table
    from sqlalchemy import delete
    from app.intel.models import VASPMatch

    trace_uuid = trace_id if isinstance(trace_id, uuid.UUID) else uuid.UUID(str(trace_id))
    case_uuid = case_id if isinstance(case_id, uuid.UUID) else uuid.UUID(str(case_id))

    await db.execute(delete(VASPMatch).where(VASPMatch.trace_id == trace_uuid))

    for r in results:
        match_obj = VASPMatch(
            trace_id=trace_uuid,
            case_id=case_uuid,
            vasp_address=r.vasp_address,
            vasp_name=r.vasp_name,
            entity_type=r.entity_type,
            hops=r.hops,
            path=r.path,
            total_value=r.total_value,
            confidence=r.confidence,
            source=r.source,
        )
        db.add(match_obj)

    await db.commit()

    logger.info(
        "find_nearest_vasps: found %d VASP matches for seed %s (trace=%s)",
        len(results), seed_address[:10], trace_id,
    )
    return results
