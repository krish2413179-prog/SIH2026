"""FastAPI router: ML-based suspicion report for a completed trace.

GET /traces/{trace_id}/ml-report
  — Loads the persisted graph, runs WalletSuspicionDetector on the seed
    wallet, and returns score, band, confidence, contributing_factors,
    detected_patterns and a node/edge summary for the fund-flow diagram.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import networkx as nx
from fastapi import APIRouter, Depends, HTTPException, status
from networkx.readwrite import json_graph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_investigator
from app.auth.models import User
from app.db.session import get_db
from app.graph.models import TraceGraph, TraceJob
from app.ml.detector import WalletSuspicionDetector

router = APIRouter(prefix="/traces", tags=["ml"])

# Singleton detector — model loaded once at import time
_detector = WalletSuspicionDetector()


@router.get(
    "/{trace_id}/ml-report",
    summary="Run ML suspicion report on a completed trace",
)
async def get_ml_report(
    trace_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_investigator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Return ML suspicion score, reasoning factors, patterns, and graph summary.

    Raises 404 if the trace job or graph does not exist.
    Raises 400 if the trace has not completed yet.
    """
    # 1. Load trace job
    job_result = await db.execute(select(TraceJob).where(TraceJob.id == trace_id))
    job: TraceJob | None = job_result.scalars().first()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trace not found")
    if job.status not in ("completed", "failed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Trace is still {job.status} — report available after completion",
        )

    # 2. Load persisted graph
    graph_result = await db.execute(
        select(TraceGraph).where(TraceGraph.trace_id == trace_id)
    )
    graph_record: TraceGraph | None = graph_result.scalars().first()

    if graph_record is None or not graph_record.graph_data:
        # No graph persisted — return rule-based score from TraceJob fields
        return _fallback_report(job)

    # 3. Reconstruct NetworkX graph
    try:
        G: nx.DiGraph = json_graph.node_link_graph(
            graph_record.graph_data,
            directed=True,
            multigraph=False,
        )
    except Exception:
        return _fallback_report(job)

    # 4. Run ML detector on seed wallet
    seed = job.wallet_address
    result = _detector.predict_wallet(
        wallet_address=seed,
        transactions=_extract_tx_list(G, seed),
        chain=job.chain,
    )

    # 5. Build graph summary for fund-flow page
    nodes_summary = [
        {
            "id": str(n),
            "entity_type": G.nodes[n].get("entity_type", "unknown"),
            "in_degree": G.in_degree(n),
            "out_degree": G.out_degree(n),
            "total_inflow": float(G.nodes[n].get("total_inflow", 0) or 0),
            "total_outflow": float(G.nodes[n].get("total_outflow", 0) or 0),
            "is_seed": str(n).lower() == seed.lower(),
        }
        for n in G.nodes()
    ]

    edges_summary = [
        {
            "source": str(u),
            "target": str(v),
            "amount": float(d.get("amount", 0) or 0),
            "is_bridge": bool(d.get("is_bridge", False)),
        }
        for u, v, d in G.edges(data=True)
    ]

    # 6. Augment contributing_factors with graph-derived signals
    contributing_factors: list[dict[str, Any]] = list(result["contributing_factors"])

    # Count mixer/tumbler nodes
    mixer_count = sum(
        1 for n in G.nodes()
        if G.nodes[n].get("entity_type", "").lower() in ("mixer", "tumbler")
    )
    if mixer_count > 0:
        contributing_factors.append({
            "feature": "mixer_interaction",
            "name": "Mixer/Tumbler Interaction",
            "value": str(mixer_count),
            "severity": "high",
            "description": (
                f"{mixer_count} mixer/tumbler address{'es' if mixer_count > 1 else ''} "
                "in transaction path (e.g. Tornado Cash)"
            ),
        })

    # Count sanctioned nodes
    sanctioned_count = sum(
        1 for n in G.nodes()
        if G.nodes[n].get("entity_type", "").lower() == "sanctioned"
        or bool(G.nodes[n].get("is_sanctioned", False))
    )
    if sanctioned_count > 0:
        contributing_factors.append({
            "feature": "sanctioned_address",
            "name": "Sanctioned Address Contact",
            "value": str(sanctioned_count),
            "severity": "high",
            "description": "Wallet transacted with OFAC/sanctioned address",
        })

    # Layering depth — maximum hop distance from seed in the graph
    max_hop = (
        max((G.nodes[n].get("hop", 0) or 0) for n in G.nodes())
        if G.number_of_nodes() > 0
        else 0
    )
    contributing_factors.append({
        "feature": "layering_depth",
        "name": "Layering Depth",
        "value": str(max_hop),
        "severity": "medium" if max_hop >= 3 else "low",
        "description": (
            f"Fund flow traced {max_hop} hop{'s' if max_hop != 1 else ''} from seed "
            "— deeper layering indicates deliberate obfuscation"
        ),
    })

    # Cross-chain bridge usage
    bridge_count = sum(
        1 for n in G.nodes()
        if G.nodes[n].get("entity_type", "").lower() == "bridge"
    )
    if bridge_count > 0:
        contributing_factors.append({
            "feature": "bridge_usage",
            "name": "Cross-chain Bridge Usage",
            "value": str(bridge_count),
            "severity": "medium",
            "description": "Funds routed through cross-chain bridges to obscure trail",
        })

    return {
        "trace_id": str(trace_id),
        "wallet_address": seed,
        "chain": job.chain,
        "risk_score": job.risk_score,
        "risk_band": job.risk_band,
        # ML output
        "suspicion_score": result["suspicion_score"],
        "suspicion_probability": result["suspicion_probability"],
        "is_suspicious": result["is_suspicious"],
        "ml_risk_band": result["risk_band"],
        "confidence": result["confidence"],
        "detected_patterns": result["detected_patterns"],
        "contributing_factors": contributing_factors,
        "model_version": result["model_version"],
        # Graph summary
        "graph": {
            "node_count": G.number_of_nodes(),
            "edge_count": G.number_of_edges(),
            "nodes": nodes_summary,
            "edges": edges_summary,
        },
        # Scoring methodology — machine-readable transparency layer
        "scoring_methodology": {
            "formula": (
                "0.35*direct_exposure + 0.20*indirect_exposure + 0.20*vasp_risk"
                " + 0.15*typology_flags + 0.10*volume_anomaly"
            ),
            "scale": "0-100",
            "band_thresholds": {"low": "0-39", "medium": "40-69", "high": "70-100"},
            "sanctioned_override": "score >= 90 if any sanctioned/darknet node in graph",
            "factors": {
                "direct_exposure": {
                    "weight": 0.35,
                    "description": "Ratio of flagged direct neighbours",
                },
                "indirect_exposure": {
                    "weight": 0.20,
                    "description": "Flagged nodes within 3 hops",
                },
                "vasp_risk_category": {
                    "weight": 0.20,
                    "description": "Risk tier of nearest VASP (CEX=0.1 to darknet=1.0)",
                },
                "typology_flags": {
                    "weight": 0.15,
                    "description": "Normalised laundering typology flag count",
                },
                "volume_anomaly": {
                    "weight": 0.10,
                    "description": "Z-score normalised transaction velocity",
                },
            },
        },
    }


def _extract_tx_list(G: nx.DiGraph, wallet: str) -> list[dict[str, Any]]:
    """Build a flat transaction list for the seed wallet from the graph."""
    w = wallet.lower()
    seed_node = next((n for n in G.nodes() if str(n).lower() == w), None)
    if seed_node is None:
        return []
    txs: list[dict[str, Any]] = []
    for _, to_node, data in G.out_edges(seed_node, data=True):
        txs.append({"from_addr": seed_node, "to_addr": to_node, **data})
    for from_node, _, data in G.in_edges(seed_node, data=True):
        txs.append({"from_addr": from_node, "to_addr": seed_node, **data})
    return txs


def _fallback_report(job: TraceJob) -> dict[str, Any]:
    """Return a minimal report using only TraceJob risk fields (no graph)."""
    score = job.risk_score or 0
    band = job.risk_band or "low"
    return {
        "trace_id": str(job.id),
        "wallet_address": job.wallet_address,
        "chain": job.chain,
        "risk_score": score,
        "risk_band": band,
        "suspicion_score": score,
        "suspicion_probability": round(score / 100, 4),
        "is_suspicious": score >= 50,
        "ml_risk_band": band,
        "confidence": 0.0,
        "detected_patterns": [],
        "contributing_factors": [],
        "model_version": "unavailable",
        "graph": {"node_count": 0, "edge_count": 0, "nodes": [], "edges": []},
        "scoring_methodology": {
            "formula": (
                "0.35*direct_exposure + 0.20*indirect_exposure + 0.20*vasp_risk"
                " + 0.15*typology_flags + 0.10*volume_anomaly"
            ),
            "scale": "0-100",
            "band_thresholds": {"low": "0-39", "medium": "40-69", "high": "70-100"},
            "sanctioned_override": "score >= 90 if any sanctioned/darknet node in graph",
            "factors": {
                "direct_exposure": {
                    "weight": 0.35,
                    "description": "Ratio of flagged direct neighbours",
                },
                "indirect_exposure": {
                    "weight": 0.20,
                    "description": "Flagged nodes within 3 hops",
                },
                "vasp_risk_category": {
                    "weight": 0.20,
                    "description": "Risk tier of nearest VASP (CEX=0.1 to darknet=1.0)",
                },
                "typology_flags": {
                    "weight": 0.15,
                    "description": "Normalised laundering typology flag count",
                },
                "volume_anomaly": {
                    "weight": 0.10,
                    "description": "Z-score normalised transaction velocity",
                },
            },
        },
    }
