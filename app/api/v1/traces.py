"""FastAPI router for trace graph endpoints.

Endpoints
---------
GET  /traces/{trace_id}/graph            — serialised graph JSON
GET  /traces/{trace_id}/status           — trace job progress + risk fields
GET  /traces/{trace_id}/live-feed        — last N addresses being fetched live
POST /traces/{trace_id}/expand           — queue an expand_graph Celery task
GET  /traces/{trace_id}/expand/status    — poll expand task result
POST /traces/{trace_id}/ai-analysis      — Mistral generative fraud analysis
GET  /traces/{trace_id}/ai-analysis      — return cached Mistral verdict

Requirements: 5.5, 15.4
"""
from __future__ import annotations

import os
import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_investigator
from app.auth.models import User
from app.db.session import get_db
from app.graph.models import TraceGraph, TraceJob

router = APIRouter(prefix="/traces", tags=["traces"])

# ---------------------------------------------------------------------------
# GET /traces/{trace_id}/live-feed
# ---------------------------------------------------------------------------

# Matches lines like:
#   [2026-09-05 19:05:12,095: INFO/ForkPoolWorker-7] HTTP Request: GET
#   https://api.etherscan.io/...&address=0xABCD...&...
_ADDR_RE = re.compile(r"&address=(0x[0-9a-fA-F]{10,}|[A-Za-z0-9]{26,})", re.IGNORECASE)
_CELERY_LOG = os.path.join(os.path.dirname(__file__), "..", "..", "..", "celery-linux.log")


def _tail_log(path: str, n_bytes: int = 65536) -> str:
    """Read the last *n_bytes* of a file safely."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - n_bytes))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


@router.get("/{trace_id}/live-feed", summary="Live address feed for loading screen")
async def get_live_feed(
    trace_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_investigator)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 20,
) -> dict[str, Any]:
    """Return the most-recently-fetched addresses from the active Celery worker.

    Tails the Celery log and extracts Etherscan/Solscan/etc. API calls made
    while processing this trace.  Returns up to *limit* unique addresses in
    reverse-chronological order (newest first).

    Also returns a ``hop`` and ``status`` field so the frontend can update
    its progress display without an extra round-trip.
    """
    # Get current trace status
    result = await db.execute(select(TraceJob).where(TraceJob.id == trace_id))
    job = result.scalars().first()
    if job is None:
        raise HTTPException(status_code=404, detail="Trace not found")

    addresses: list[str] = []
    if job.status == "running":
        tail = _tail_log(_CELERY_LOG)
        # Extract addresses, deduplicate preserving order (newest first)
        seen: set[str] = set()
        for match in reversed(_ADDR_RE.findall(tail)):
            addr = match
            if addr not in seen:
                seen.add(addr)
                addresses.append(addr)
            if len(addresses) >= limit:
                break

    return {
        "trace_id": str(trace_id),
        "status": job.status,
        "current_hop": job.current_hop,
        "estimated_pct": job.estimated_pct,
        "addresses": addresses,
    }


# ---------------------------------------------------------------------------
# GET /traces/{trace_id}/llm-analysis
# ---------------------------------------------------------------------------


@router.get(
    "/{trace_id}/llm-analysis",
    summary="Get LLM suspicion analysis for all wallets in a trace",
)
async def get_llm_analysis(
    trace_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_investigator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Return per-wallet suspicion scores, labels, reasons, and flags.

    Results come from the in-process cache if available (populated when the
    trace ran).  If the cache is cold (e.g. after a worker restart), the
    graph node attributes ``llm_score`` / ``llm_label`` / ``llm_reason`` /
    ``llm_flags`` stored in the graph_data JSONB are used instead.

    Returns ``{"wallets": [...], "source": "cache"|"graph"}``
    """
    from app.risk.llm_analyst import get_cached, WalletAnalysis

    # 1. Try in-memory cache first (cheap)
    cached = get_cached(str(trace_id))
    if cached:
        return {
            "trace_id": str(trace_id),
            "source":   "cache",
            "wallets":  [
                {
                    "address":         w.address,
                    "suspicion_score": w.suspicion_score,
                    "label":           w.label,
                    "reason":          w.reason,
                    "flags":           w.flags,
                }
                for w in cached
            ],
        }

    # 2. Fall back to graph node attributes (persisted in JSONB)
    result = await db.execute(
        select(TraceGraph).where(TraceGraph.trace_id == trace_id)
    )
    record = result.scalars().first()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No graph found for trace_id {trace_id}",
        )

    wallets = []
    for node in (record.graph_data or {}).get("nodes", []):
        if "llm_score" in node:
            wallets.append({
                "address":         str(node.get("id", "")),
                "suspicion_score": int(node["llm_score"]),
                "label":           str(node.get("llm_label", "unknown")),
                "reason":          str(node.get("llm_reason", "")),
                "flags":           list(node.get("llm_flags", [])),
            })

    return {
        "trace_id": str(trace_id),
        "source":   "graph",
        "wallets":  wallets,
    }

# ---------------------------------------------------------------------------
# GET /traces/{trace_id}/graph
# ---------------------------------------------------------------------------


@router.get("/{trace_id}/graph", summary="Retrieve serialised transaction graph")
async def get_trace_graph(
    trace_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_investigator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    result = await db.execute(
        select(TraceGraph).where(TraceGraph.trace_id == trace_id)
    )
    record = result.scalars().first()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No graph found for trace_id {trace_id}",
        )
    return record.graph_data


# ---------------------------------------------------------------------------
# GET /traces/{trace_id}/status
# ---------------------------------------------------------------------------


@router.get("/{trace_id}/status", summary="Retrieve trace job status and progress")
async def get_trace_status(
    trace_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_investigator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    result = await db.execute(
        select(TraceJob).where(TraceJob.id == trace_id)
    )
    job = result.scalars().first()
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No trace job found with id {trace_id}",
        )
    return {
        "trace_id":     job.id,
        "status":       job.status,
        "current_hop":  job.current_hop,
        "max_hops":     job.max_hops,
        "estimated_pct": job.estimated_pct,
        "enqueued_at":  job.enqueued_at,
        "started_at":   job.started_at,
        "completed_at": job.completed_at,
        "risk_score":   job.risk_score,
        "risk_band":    job.risk_band,
    }


# ---------------------------------------------------------------------------
# POST /traces/{trace_id}/expand
# ---------------------------------------------------------------------------


@router.post(
    "/{trace_id}/expand",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a one-hop graph expansion from leaf nodes",
    description=(
        "Enqueues an expand_graph Celery task that deepens the existing "
        "transaction graph by one additional BFS hop from all leaf nodes "
        "(wallets with no outgoing edges explored yet). "
        "Returns the Celery task ID immediately; poll /expand/status to "
        "check completion."
    ),
)
async def expand_trace_graph(
    trace_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_investigator)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    # Verify the trace job exists and is completed
    result = await db.execute(
        select(TraceJob).where(TraceJob.id == trace_id)
    )
    job = result.scalars().first()
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"TraceJob {trace_id} not found",
        )
    if job.status not in ("completed", "failed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"TraceJob is currently '{job.status}' — can only expand completed traces",
        )

    # Verify a graph exists
    graph_result = await db.execute(
        select(TraceGraph).where(TraceGraph.trace_id == trace_id)
    )
    if graph_result.scalars().first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No graph persisted for trace_id {trace_id} — run the trace first",
        )

    from app.tasks.trace_tasks import expand_graph
    task = expand_graph.apply_async(
        args=[str(trace_id)],
        queue="traces",
    )

    return {"celery_task_id": task.id, "trace_id": str(trace_id)}


# ---------------------------------------------------------------------------
# GET /traces/{trace_id}/expand/status
# ---------------------------------------------------------------------------


@router.get(
    "/{trace_id}/expand/status",
    summary="Poll the status of an expand_graph task",
)
async def get_expand_status(
    trace_id: uuid.UUID,
    celery_task_id: str,
    current_user: Annotated[User, Depends(require_investigator)],
) -> dict[str, Any]:
    """Poll Celery for the result of an expand_graph task.

    Query param: ``celery_task_id`` — returned by POST /expand.

    States returned: ``PENDING``, ``STARTED``, ``SUCCESS``, ``FAILURE``.
    On ``SUCCESS`` the result dict contains ``nodes``, ``edges``, ``new_nodes``.
    """
    from celery.result import AsyncResult
    from app.tasks.celery_app import celery_app

    ar = AsyncResult(celery_task_id, app=celery_app)
    state = ar.state

    response: dict[str, Any] = {
        "trace_id":       str(trace_id),
        "celery_task_id": celery_task_id,
        "state":          state,
    }

    if state == "SUCCESS":
        response["result"] = ar.result
    elif state == "FAILURE":
        response["error"] = str(ar.result)

    return response

# ---------------------------------------------------------------------------
# POST /traces/{trace_id}/ai-analysis   — run Mistral generative analysis
# GET  /traces/{trace_id}/ai-analysis   — return cached verdict
# ---------------------------------------------------------------------------


def _verdict_to_dict(v: "Any") -> dict[str, Any]:
    """Serialise a MistralVerdict dataclass to a plain dict."""
    return {
        "is_fraud":        v.is_fraud,
        "confidence":      v.confidence,
        "refined_score":   v.refined_score,
        "verdict_label":   v.verdict_label,
        "crime_type":      v.crime_type,
        "summary":         v.summary,
        "evidence_chain":  v.evidence_chain,
        "missing_data":    v.missing_data,
        "recommendations": v.recommendations,
        "prompt_tier":     v.prompt_tier,
    }


@router.post(
    "/{trace_id}/ai-analysis",
    status_code=status.HTTP_200_OK,
    summary="Run Mistral generative fraud analysis for a trace",
    description=(
        "Calls Mistral AI with a tier-appropriate prompt (low/ambiguous/high-risk) "
        "based on the existing rule-based risk score and the full graph metrics. "
        "Returns a structured fraud verdict with refined score, crime type, "
        "evidence chain, and actionable recommendations. Results are cached "
        "in-process for the lifetime of the worker."
    ),
)
async def run_ai_analysis(
    trace_id:     uuid.UUID,
    current_user: Annotated[User, Depends(require_investigator)],
    db:           Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    # Load TraceJob for wallet address + chain + rule score
    job_result = await db.execute(select(TraceJob).where(TraceJob.id == trace_id))
    job = job_result.scalars().first()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"TraceJob {trace_id} not found")

    # Load persisted graph
    graph_result = await db.execute(select(TraceGraph).where(TraceGraph.trace_id == trace_id))
    graph_record = graph_result.scalars().first()
    if graph_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"No graph found for trace_id {trace_id} — run the trace first")

    # Reconstruct nx.DiGraph from stored JSON
    from networkx.readwrite import json_graph as jg
    import networkx as nx
    try:
        G: nx.DiGraph = jg.node_link_graph(
            graph_record.graph_data,
            directed=True,
            multigraph=False,
        )
    except Exception:
        G = nx.DiGraph()

    rule_score = int(job.risk_score or 50)

    from app.risk.mistral_analyst import analyse_trace, invalidate_cache
    invalidate_cache(str(trace_id))

    verdict = await analyse_trace(
        trace_id=str(trace_id),
        wallet=job.wallet_address,
        chain=job.chain,
        G=G,
        rule_score=rule_score,
    )

    return {
        "trace_id": str(trace_id),
        "wallet":   job.wallet_address,
        "chain":    job.chain,
        "rule_score": rule_score,
        **_verdict_to_dict(verdict),
    }


@router.get(
    "/{trace_id}/ai-analysis",
    summary="Return cached Mistral fraud verdict (no new API call)",
)
async def get_ai_analysis(
    trace_id:     uuid.UUID,
    current_user: Annotated[User, Depends(require_investigator)],
) -> dict[str, Any]:
    from app.risk.mistral_analyst import get_cached
    verdict = get_cached(str(trace_id))
    if verdict is None:
        return {"trace_id": str(trace_id), "cached": False, "detail": "No AI analysis run yet"}
    return {"trace_id": str(trace_id), "cached": True, **_verdict_to_dict(verdict)}


@router.get(
    "/{trace_id}/nearest-vasps",
    summary="Get ranked nearest VASPs / exchanges for LEA disclosure routing",
)
async def get_nearest_vasps(
    trace_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Return nearest Virtual Asset Service Providers (exchanges, mixers, bridges)
    reachable from the seed wallet, ordered by hop count and value.
    """
    from sqlalchemy import text
    query = text(
        """
        SELECT vasp_address, vasp_name, entity_type, hops, path, total_value, confidence, source, created_at
        FROM vasp_matches
        WHERE trace_id = CAST(:trace_id AS UUID)
        ORDER BY hops ASC, total_value DESC, confidence DESC
        """
    )
    result = await db.execute(query, {"trace_id": str(trace_id)})
    rows = result.fetchall()

    # Fallback for traces completed prior to persistence fix
    if not rows:
        try:
            job_result = await db.execute(select(TraceJob).where(TraceJob.id == trace_id))
            job = job_result.scalars().first()
            if job and job.status == "completed":
                from app.graph.persistence import get_graph
                from app.graph.vasp_finder import find_nearest_vasps
                G = await get_graph(trace_id=job.id, db=db)
                if G and G.number_of_nodes() > 0:
                    await find_nearest_vasps(
                        G=G,
                        seed_address=job.wallet_address,
                        chain=job.chain,
                        trace_id=job.id,
                        case_id=job.case_id,
                        db=db,
                    )
                    # Re-query after find_nearest_vasps persisted the matches
                    result = await db.execute(query, {"trace_id": str(trace_id)})
                    rows = result.fetchall()
        except Exception:
            logger.exception("get_nearest_vasps fallback error for trace %s", trace_id)

    matches = [
        {
            "vasp_address": r.vasp_address,
            "vasp_name": r.vasp_name,
            "entity_type": r.entity_type,
            "hops": r.hops,
            "path": r.path,
            "total_value": float(r.total_value),
            "confidence": float(r.confidence),
            "source": r.source,
            "created_at": r.created_at.isoformat() if hasattr(r.created_at, "isoformat") else str(r.created_at),
        }
        for r in rows
    ]

    return {
        "trace_id": str(trace_id),
        "total_matches": len(matches),
        "nearest_vasps": matches,
    }

