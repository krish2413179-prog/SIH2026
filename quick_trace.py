"""Quick trace - fetch only direct transactions of each pending wallet (no BFS expansion)."""
import asyncio, json, uuid
from datetime import datetime, timezone
from decimal import Decimal
import networkx as nx
from networkx.readwrite import json_graph
from sqlalchemy import select, or_
from app.db.session import AsyncSessionLocal
from app.graph.models import TraceJob, TraceGraph
from app.adapters.registry import get_adapter

async def run():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(TraceJob).where(or_(TraceJob.status=='queued',TraceJob.status=='running')))
        jobs = result.scalars().all()
        print(f'{len(jobs)} pending traces')
        
        for j in jobs:
            print(f'  Tracing {j.wallet_address} on {j.chain}...')
            j.status = 'running'
            await db.flush()
            
            try:
                adapter = get_adapter(j.chain)
                # Fetch only the seed wallet's transactions (no expansion)
                txs = await adapter.get_transactions(j.wallet_address, page=1, page_size=50)
                print(f'    Got {len(txs)} transactions')
                
                # Build graph from just these transactions
                G = nx.DiGraph()
                G.add_node(j.wallet_address, chain=j.chain, entity_type='unknown',
                          in_degree=0, out_degree=0, total_inflow=0.0, total_outflow=0.0,
                          first_seen=None, last_seen=None)
                
                for tx in txs:
                    if tx.from_addr and tx.to_addr:
                        if tx.from_addr not in G:
                            G.add_node(tx.from_addr, chain=j.chain, entity_type='unknown',
                                      in_degree=0, out_degree=0, total_inflow=0.0, total_outflow=0.0,
                                      first_seen=None, last_seen=None)
                        if tx.to_addr not in G:
                            G.add_node(tx.to_addr, chain=j.chain, entity_type='unknown',
                                      in_degree=0, out_degree=0, total_inflow=0.0, total_outflow=0.0,
                                      first_seen=None, last_seen=None)
                        G.add_edge(tx.from_addr, tx.to_addr,
                                  tx_hash=tx.tx_hash,
                                  amount=float(tx.amount),
                                  fee=float(tx.fee),
                                  timestamp=tx.timestamp.isoformat(),
                                  chain=j.chain,
                                  is_bridge=tx.is_bridge,
                                  bridge_protocol=tx.bridge_protocol)
                
                # Update node metrics
                for node in G.nodes():
                    in_edges = list(G.in_edges(node, data=True))
                    out_edges = list(G.out_edges(node, data=True))
                    G.nodes[node]['in_degree'] = len(in_edges)
                    G.nodes[node]['out_degree'] = len(out_edges)
                    G.nodes[node]['total_inflow'] = sum(float(d.get('amount',0)) for _,_,d in in_edges)
                    G.nodes[node]['total_outflow'] = sum(float(d.get('amount',0)) for _,_,d in out_edges)
                
                print(f'    Built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges')
                
                gd = json.loads(json.dumps(json_graph.node_link_data(G), default=str))
                
                existing = await db.execute(select(TraceGraph).where(TraceGraph.trace_id==j.id))
                rec = existing.scalars().first()
                if rec:
                    rec.graph_data = gd
                else:
                    db.add(TraceGraph(id=uuid.uuid4(), trace_id=j.id, case_id=j.case_id,
                                     wallet_address=j.wallet_address, chain=j.chain, graph_data=gd))
                
                j.status = 'completed'
                j.completed_at = datetime.now(timezone.utc)
                j.estimated_pct = 100.0
                print(f'    Saved graph!')
                
            except Exception as e:
                print(f'    FAILED: {e}')
                j.status = 'failed'
                j.completed_at = datetime.now(timezone.utc)
            
            await db.flush()
        
        await db.commit()
        print('All done!')

asyncio.run(run())
