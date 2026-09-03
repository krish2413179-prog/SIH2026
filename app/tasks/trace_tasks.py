"""Celery tasks: run_trace and expand_graph.

run_trace    — full BFS trace from scratch with min_nodes=20 / deadline=300s
expand_graph — one additional BFS hop from leaf nodes of a completed graph

Requirements: 5.5, 15.4
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

from celery.exceptions import MaxRetriesExceededError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared sync-session factory
# ---------------------------------------------------------------------------


def _get_sync_session_factory() -> sessionmaker:
    sync_url = os.environ.get("DATABASE_SYNC_URL")
    if not sync_url:
        from app.config import get_settings
        sync_url = get_settings().database_sync_url
    engine = create_engine(
        sync_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_recycle=3600,
    )
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _get_trace_job_model():
    from app.graph.models import TraceJob
    return TraceJob


# ---------------------------------------------------------------------------
# run_trace
# ---------------------------------------------------------------------------


@celery_app.task(
    name="tasks.trace.run_trace",
    bind=True,
    max_retries=3,
    # 7-minute soft timeout so Celery doesn't kill a trace that's near the
    # 5-minute deadline but still writing results to the DB.
    soft_time_limit=420,
    time_limit=480,
)
def run_trace(self, trace_job_id: str) -> None:  # type: ignore[override]
    """Full blockchain trace for the given TraceJob.

    Keeps expanding BFS hops until the graph has >= 20 unique wallet nodes
    or 5 minutes elapse, then persists whatever was built and marks the job
    completed.
    """
    job_uuid = uuid.UUID(trace_job_id)
    SyncSession = _get_sync_session_factory()

    with SyncSession() as db:
        try:
            TraceJob = _get_trace_job_model()
            job = db.execute(
                select(TraceJob).where(TraceJob.id == job_uuid)
            ).scalars().first()

            if job is None:
                logger.error("run_trace: TraceJob %s not found — skipping", trace_job_id)
                return

            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            db.flush()
            db.commit()

            from app.adapters.registry import get_adapter
            adapter = get_adapter(job.chain)

            from app.graph.builder import build_graph

            async def _build_and_save() -> object:
                G = await build_graph(
                    seed_address=job.wallet_address,
                    chain=job.chain,
                    adapter=adapter,
                    max_hops=job.max_hops,
                    # ── new params ─────────────────────────────────────
                    min_nodes=20,
                    deadline_seconds=300.0,
                )

                # ── Intel Tagging & Nearest VASP Identification ──────
                try:
                    engine, AsyncSessionLocal = _make_async_engine_session()
                    async with AsyncSessionLocal() as async_db:
                        from app.intel.seed_known_addresses import seed_intel_addresses
                        await seed_intel_addresses(async_db)

                        from app.graph.vasp_finder import find_nearest_vasps
                        vasp_matches = await find_nearest_vasps(
                            G=G,
                            seed_address=job.wallet_address,
                            chain=job.chain,
                            trace_id=job.id,
                            case_id=job.case_id,
                            db=async_db,
                        )
                        logger.info("run_trace: identified %d nearest VASP matches", len(vasp_matches))
                    await engine.dispose()
                except Exception:
                    logger.warning("run_trace: VASP finder step failed — continuing trace", exc_info=True)

                # ── LLM suspicion analysis ──────────────────────────
                try:
                    from app.risk.llm_analyst import analyse_graph, invalidate_cache
                    invalidate_cache(str(job.id))
                    analyses = await analyse_graph(
                        trace_id=str(job.id),
                        seed_address=job.wallet_address,
                        chain=job.chain,
                        G=G,
                    )
                    # Annotate graph nodes with LLM results
                    analysis_map = {a.address.lower(): a for a in analyses}
                    for node in G.nodes():
                        a = analysis_map.get(str(node).lower())
                        if a:
                            G.nodes[node]["llm_score"]  = a.suspicion_score
                            G.nodes[node]["llm_label"]  = a.label
                            G.nodes[node]["llm_reason"] = a.reason
                            G.nodes[node]["llm_flags"]  = a.flags
                            # Promote entity_type for highly suspicious wallets
                            if a.label == "highly_suspicious":
                                G.nodes[node]["entity_type"] = "flagged"
                except Exception:
                    logger.warning(
                        "run_trace: LLM analysis failed for %s — continuing without it",
                        job.wallet_address, exc_info=True,
                    )

                await _save_graph_async(
                    trace_id=job.id,
                    case_id=job.case_id,
                    wallet_address=job.wallet_address,
                    chain=job.chain,
                    G=G,
                )
                return G

            G = asyncio.run(_build_and_save())

            with SyncSession() as final_db:
                final_job = final_db.execute(
                    select(TraceJob).where(TraceJob.id == job_uuid)
                ).scalars().first()
                if final_job is not None:
                    final_job.status = "completed"
                    final_job.completed_at = datetime.now(timezone.utc)
                    final_job.estimated_pct = 100.0

                    # ── Compute Risk Score & Band ─────────────────────
                    try:
                        from app.risk.scorer import compute_risk_score, classify_risk_band
                        # Count flagged/high-risk nodes in graph
                        total_nodes = G.number_of_nodes() or 1
                        flagged_nodes = sum(
                            1 for _, attrs in G.nodes(data=True)
                            if attrs.get("entity_type") in ("sanctioned", "mixer", "darknet", "scam", "ransomware", "flagged")
                        )
                        direct_exp = min(1.0, flagged_nodes / total_nodes)
                        
                        # Has direct mixer/sanctions interaction?
                        has_sanctioned = any(
                            attrs.get("entity_type") in ("sanctioned", "darknet")
                            for _, attrs in G.nodes(data=True)
                        )
                        has_mixer = any(
                            attrs.get("entity_type") == "mixer"
                            for _, attrs in G.nodes(data=True)
                        )

                        vasp_weight = 1.0 if has_sanctioned else (0.9 if has_mixer else 0.2)
                        
                        score = compute_risk_score(
                            direct_exposure=direct_exp,
                            indirect_exposure=direct_exp * 0.5,
                            vasp_risk_category=vasp_weight,
                            typology_flags=min(1.0, flagged_nodes / 5.0),
                            volume_anomaly=0.3,
                        )
                        if has_sanctioned:
                            score = max(score, 90)

                        final_job.risk_score = score
                        final_job.risk_band = classify_risk_band(score)
                    except Exception:
                        logger.warning("run_trace: failed to compute risk score for %s", trace_job_id, exc_info=True)

                    final_db.commit()

            logger.info(
                "run_trace: TraceJob %s completed (nodes=%d, edges=%d)",
                trace_job_id, G.number_of_nodes(), G.number_of_edges(),
            )

        except Exception as exc:
            logger.exception("run_trace: TraceJob %s failed: %s", trace_job_id, exc)
            try:
                with SyncSession() as fail_db:
                    TraceJob = _get_trace_job_model()
                    failed_job = fail_db.execute(
                        select(TraceJob).where(TraceJob.id == job_uuid)
                    ).scalars().first()
                    if failed_job is not None:
                        failed_job.status = "failed"
                        failed_job.completed_at = datetime.now(timezone.utc)
                        fail_db.commit()
            except Exception:
                logger.exception("run_trace: could not persist failure for %s", trace_job_id)
            try:
                raise self.retry(exc=exc, countdown=30)
            except MaxRetriesExceededError:
                logger.error("run_trace: %s exhausted retries — permanently failed", trace_job_id)


# ---------------------------------------------------------------------------
# expand_graph
# ---------------------------------------------------------------------------


@celery_app.task(
    name="tasks.trace.expand_graph",
    bind=True,
    max_retries=2,
    soft_time_limit=180,
    time_limit=240,
)
def expand_graph(self, trace_job_id: str) -> dict:  # type: ignore[override]
    """Expand an already-completed trace graph by one additional BFS hop.

    Loads the persisted graph for *trace_job_id*, runs
    ``build_graph_expand()`` from all leaf nodes (wallets with no outgoing
    edges in the current graph), and overwrites the stored graph_data with
    the expanded result.

    Returns a summary dict: ``{"nodes": int, "edges": int, "new_nodes": int}``.
    """
    job_uuid = uuid.UUID(trace_job_id)
    SyncSession = _get_sync_session_factory()

    try:
        TraceJob = _get_trace_job_model()
        with SyncSession() as db:
            job = db.execute(
                select(TraceJob).where(TraceJob.id == job_uuid)
            ).scalars().first()
            if job is None:
                raise ValueError(f"TraceJob {trace_job_id} not found")
            chain         = job.chain
            wallet_address = job.wallet_address
            case_id       = job.case_id

        from app.adapters.registry import get_adapter
        from app.graph.builder import build_graph_expand

        adapter = get_adapter(chain)

        async def _expand_and_save() -> dict:
            from app.graph.persistence import get_graph
            # load existing graph
            engine, AsyncSessionLocal = _make_async_engine_session()
            try:
                async with AsyncSessionLocal() as async_db:
                    G = await get_graph(job_uuid, async_db)
                if G is None:
                    raise ValueError(f"No graph found for TraceJob {trace_job_id}")

                nodes_before = G.number_of_nodes()
                G = await build_graph_expand(
                    G=G,
                    chain=chain,
                    adapter=adapter,
                    deadline_seconds=120.0,
                )
                new_nodes = G.number_of_nodes() - nodes_before

                # persist expanded graph
                async with AsyncSessionLocal() as async_db:
                    try:
                        from app.graph.persistence import save_graph
                        await save_graph(
                            trace_id=job_uuid,
                            case_id=case_id,
                            wallet_address=wallet_address,
                            chain=chain,
                            G=G,
                            db=async_db,
                        )
                        await async_db.commit()
                    except Exception:
                        await async_db.rollback()
                        raise
            finally:
                await engine.dispose()

            return {
                "nodes":     G.number_of_nodes(),
                "edges":     G.number_of_edges(),
                "new_nodes": new_nodes,
            }

        result = asyncio.run(_expand_and_save())
        logger.info(
            "expand_graph: TraceJob %s expanded to %d nodes (+%d), %d edges",
            trace_job_id, result["nodes"], result["new_nodes"], result["edges"],
        )
        return result

    except Exception as exc:
        logger.exception("expand_graph: %s failed: %s", trace_job_id, exc)
        try:
            raise self.retry(exc=exc, countdown=15)
        except MaxRetriesExceededError:
            logger.error("expand_graph: %s exhausted retries", trace_job_id)
            return {"nodes": 0, "edges": 0, "new_nodes": 0, "error": str(exc)}


# ---------------------------------------------------------------------------
# Shared async helpers
# ---------------------------------------------------------------------------


def _make_async_engine_session():
    """Create a fresh async engine + sessionmaker for the current event loop.

    Always call inside asyncio.run() to avoid cross-loop asyncpg issues.
    """
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker as sa_sessionmaker

    async_url = os.environ.get("DATABASE_URL")
    if not async_url:
        from app.config import get_settings
        async_url = get_settings().database_url

    engine = create_async_engine(
        async_url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=5,
    )
    AsyncSessionLocal = sa_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return engine, AsyncSessionLocal


async def _save_graph_async(
    trace_id: uuid.UUID,
    case_id: uuid.UUID,
    wallet_address: str,
    chain: str,
    G,
) -> None:
    """Persist graph using a fresh async engine scoped to the current loop."""
    from app.graph.persistence import save_graph

    engine, AsyncSessionLocal = _make_async_engine_session()
    try:
        async with AsyncSessionLocal() as async_db:
            try:
                await save_graph(
                    trace_id=trace_id,
                    case_id=case_id,
                    wallet_address=wallet_address,
                    chain=chain,
                    G=G,
                    db=async_db,
                )
                await async_db.commit()
            except Exception:
                await async_db.rollback()
                raise
    finally:
        await engine.dispose()
