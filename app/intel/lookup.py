"""Fast lookup service for the known_addresses table.

Provides:
  - tag_graph_nodes: Bulk queries known_addresses for all nodes in a NetworkX graph
    and attaches entity_type, entity_name, and confidence to the nodes.
  - lookup_address: Single address lookup returning all matching KnownAddress rows.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.intel.models import KnownAddress

if TYPE_CHECKING:
    import networkx as nx

logger = logging.getLogger(__name__)


async def lookup_address(
    address: str,
    chain: str | None,
    db: AsyncSession,
) -> list[KnownAddress]:
    """Look up a single address across all intelligence sources.

    Matches case-insensitively.  If *chain* is provided, returns matches where
    ``KnownAddress.chain`` is NULL (applies to all chains) OR matches *chain*.
    Results are ordered by confidence descending.
    """
    addr_lower = address.strip().lower()

    stmt = select(KnownAddress).where(
        func.lower(KnownAddress.address) == addr_lower
    )

    if chain:
        stmt = stmt.where(
            or_(
                KnownAddress.chain.is_(None),
                func.upper(KnownAddress.chain) == chain.upper(),
            )
        )

    stmt = stmt.order_by(KnownAddress.confidence.desc())

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def tag_graph_nodes(
    G: nx.DiGraph,
    chain: str,
    db: AsyncSession,
) -> dict[str, KnownAddress]:
    """Bulk tag all nodes in *G* against the known_addresses table.

    Mutates node attributes in *G* in-place when a match is found:
      - ``entity_type`` = tag.entity_type
      - ``entity_name`` = tag.entity_name
      - ``intel_source`` = tag.source
      - ``intel_confidence`` = tag.confidence
      - ``risk_category`` = tag.risk_category

    Returns a dictionary mapping ``address -> best_matching_KnownAddress``.
    """
    nodes = list(G.nodes())
    if not nodes:
        return {}

    # Lower-case mapping for lookup
    node_lower_map = {n.lower(): n for n in nodes}
    node_lowers = list(node_lower_map.keys())

    # Bulk query in chunks of 500 to avoid SQL parameter limits
    chunk_size = 500
    matched_tags: dict[str, KnownAddress] = {}

    for i in range(0, len(node_lowers), chunk_size):
        chunk = node_lowers[i : i + chunk_size]
        stmt = (
            select(KnownAddress)
            .where(func.lower(KnownAddress.address).in_(chunk))
            .where(
                or_(
                    KnownAddress.chain.is_(None),
                    func.upper(KnownAddress.chain) == chain.upper(),
                )
            )
            .order_by(KnownAddress.confidence.desc())
        )

        result = await db.execute(stmt)
        rows = result.scalars().all()

        for row in rows:
            orig_addr = node_lower_map.get(row.address.lower())
            if orig_addr and orig_addr not in matched_tags:
                # Store highest-confidence match first
                matched_tags[orig_addr] = row

    # Annotate NetworkX graph nodes
    for orig_addr, tag in matched_tags.items():
        if orig_addr in G:
            G.nodes[orig_addr].update({
                "entity_type": tag.entity_type,
                "entity_name": tag.entity_name,
                "intel_source": tag.source,
                "intel_confidence": tag.confidence,
                "risk_category": tag.risk_category,
            })

    logger.info(
        "tag_graph_nodes: tagged %d / %d nodes for chain %s",
        len(matched_tags), len(nodes), chain,
    )
    return matched_tags
