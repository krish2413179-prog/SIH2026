"""Graph persistence helpers — serialize/deserialize NetworkX graphs to JSONB.

Requirements: 5.5
"""
from __future__ import annotations

import uuid

import networkx as nx
from networkx.readwrite import json_graph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.graph.models import TraceGraph


async def save_graph(
    trace_id: uuid.UUID,
    case_id: uuid.UUID,
    wallet_address: str,
    chain: str,
    G: nx.DiGraph,
    db: AsyncSession,
) -> TraceGraph:
    """Upsert graph data into trace_graphs table.

    If a TraceGraph record already exists for *trace_id* its ``graph_data``
    is updated in-place (upsert semantics).  Otherwise a new record is
    inserted.

    Args:
        trace_id:       UUID of the parent TraceJob.
        case_id:        UUID of the parent case (denormalised).
        wallet_address: Seed wallet address used when building the graph.
        chain:          Blockchain identifier (e.g. "ETH", "BTC").
        G:              NetworkX DiGraph to serialise.
        db:             Active async SQLAlchemy session.

    Returns:
        The created or updated :class:`~app.graph.models.TraceGraph` ORM record.
    """
    result = await db.execute(
        select(TraceGraph).where(TraceGraph.trace_id == trace_id)
    )
    existing = result.scalars().first()

    # Trim heavy per-node attributes that bloat the JSONB payload before serializing.
    # We keep the attributes the frontend and risk engine actually use; raw tx lists
    # (which can be hundreds of KB per node) are dropped.
    _KEEP_NODE_ATTRS = {
        "entity_type", "label", "vasp_name", "risk_score", "risk_band",
        "cluster_id", "balance", "chain", "first_seen", "last_seen",
        "llm_score", "llm_label", "llm_reason", "llm_flags",
        "is_seed", "hop",
    }
    for _, attrs in G.nodes(data=True):
        for key in list(attrs.keys()):
            if key not in _KEEP_NODE_ATTRS:
                del attrs[key]

    # Serialize graph — convert Decimal and datetime to JSON-safe types
    import json
    raw_data = json_graph.node_link_data(G)
    # Use json round-trip with a default serializer to handle Decimal/datetime
    graph_data = json.loads(json.dumps(raw_data, default=str))

    if existing:
        existing.graph_data = graph_data
        record = existing
    else:
        record = TraceGraph(
            trace_id=trace_id,
            case_id=case_id,
            wallet_address=wallet_address,
            chain=chain,
            graph_data=graph_data,
        )
        db.add(record)

    await db.flush()
    return record


async def get_graph(
    trace_id: uuid.UUID,
    db: AsyncSession,
) -> nx.DiGraph | None:
    """Load and deserialize a graph by *trace_id*.

    Args:
        trace_id: UUID of the TraceJob whose graph should be retrieved.
        db:       Active async SQLAlchemy session.

    Returns:
        A reconstructed :class:`networkx.DiGraph`, or ``None`` if no record
        exists for the given *trace_id*.
    """
    result = await db.execute(
        select(TraceGraph).where(TraceGraph.trace_id == trace_id)
    )
    record = result.scalars().first()

    if record is None:
        return None

    return json_graph.node_link_graph(
        record.graph_data,
        directed=True,
        multigraph=False,
    )
