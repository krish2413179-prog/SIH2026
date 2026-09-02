"""Run all pending trace jobs directly without Celery."""
import asyncio
import uuid
import networkx as nx
from datetime import datetime, timezone
from sqlalchemy import select, or_
from networkx.readwrite import json_graph
from app.db.session import AsyncSessionLocal
from app.graph.models import TraceJob, TraceGraph
from app.graph.builder import build_graph
from app.adapters.registry import get_adapter

async def run_all_pending():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(TraceJob).where(or_(TraceJob.status == 'queued', TraceJob.status == 'running'))
        )
        jobs = result.scalars().all()
        print(f'Found {len(jobs)} pending traces')

        for j in jobs:
            print(f'  Tracing {j.wallet_address} on {j.chain}...')
            j.status = 'running'
            j.started_at = datetime.now(timezone.utc)
            await db.flush()

            try:
                adapter = get_adapter(j.chain)
                G = await build_graph(j.wallet_address, j.chain, adapter, max_hops=j.max_hops)
                print(f'    Built graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges')

                # Save graph
                existing = await db.execute(select(TraceGraph).where(TraceGraph.trace_id == j.id))
                rec = existing.scalars().first()
                # Convert graph data to JSON-safe format (Decimal → float)
                import json
                raw_data = json_graph.node_link_data(G)
                graph_data = json.loads(json.dumps(raw_data, default=float))
                if rec:
                    rec.graph_data = graph_data
                else:
                    db.add(TraceGraph(
                        id=uuid.uuid4(), trace_id=j.id, case_id=j.case_id,
                        wallet_address=j.wallet_address, chain=j.chain,
                        graph_data=graph_data
                    ))

                j.status = 'completed'
                j.completed_at = datetime.now(timezone.utc)
                j.estimated_pct = 100.0
                print(f'    Completed: {G.number_of_nodes()} nodes')

            except Exception as e:
                print(f'    Failed: {e}')
                j.status = 'failed'
                j.completed_at = datetime.now(timezone.utc)

            await db.flush()

        await db.commit()
        print('Done')

asyncio.run(run_all_pending())
