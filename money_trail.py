import asyncio
import logging
from dotenv import load_dotenv
import networkx as nx

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("MoneyTrail")

async def follow_the_money(address: str, chain: str = "ETH"):
    logger.info(f"💰 Following the money from {address} on {chain}...")

    try:
        from app.adapters.registry import get_adapter
        from app.graph.builder import build_graph

        # 1. Build a deep graph to find the exit point
        adapter = get_adapter(chain)
        logger.info("📦 Building deep graph (up to 6 hops) to find cash-out points...")
        G = await build_graph(
            seed_address=address,
            chain=chain,
            adapter=adapter,
            max_hops=6,
            min_nodes=100
        )
        logger.info(f"✅ Graph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

        # Normalize seed address
        seed_node = address.lower()
        if seed_node not in G:
            candidates = [n for n in G.nodes() if str(n).lower() == seed_node]
            if candidates:
                seed_node = candidates[0]
            else:
                logger.error(f"Seed address {address} not found in graph.")
                return

        # 2. Find the "Sinks" (Wallets where money ends up)
        sinks = []
        for node in G.nodes():
            attrs = G.nodes[node]
            in_flow = attrs.get("total_inflow", 0.0)
            out_flow = attrs.get("total_outflow", 0.0)

            # If wallet received significant funds but didn't send them all out
            if in_flow > 0 and (in_flow - out_flow) > (in_flow * 0.1):
                dist = 99
                try:
                    dist = len(nx.shortest_path(G, source=seed_node, target=node)) - 1
                except:
                    pass

                sinks.append({
                    "address": node,
                    "net_gain": in_flow - out_flow,
                    "total_in": in_flow,
                    "hops": dist
                })

        # Sort sinks by net gain (descending)
        sinks.sort(key=lambda x: x["net_gain"], reverse=True)

        # 3. Report the most likely cash-out points
        print("\n" + "="*60)
        print(f"MONEY TRAIL ANALYSIS: {address}")
        print("="*60)

        if not sinks:
            print("No significant accumulation points found. Funds may have been split or moved out of trace range.")
        else:
            print(f"Top {min(len(sinks), 5)} Potential Cash-out Points (Sinks):")
            for i, s in enumerate(sinks[:5], 1):
                print(f"\n{i}. Address: {s['address']}")
                print(f"   Net Accumulation: {s['net_gain']:.4f} ETH/Token")
                print(f"   Total Inflow:    {s['total_in']:.4f}")
                print(f"   Distance:        {s['hops']} hops")

                if s['hops'] < 3:
                    print("   Status: Immediate Counterparty")
                elif s['hops'] < 6:
                    print("   Status: Layered Destination")
                else:
                    print("   Status: Remote Destination")

        print("="*60)
        print("Forensic Tip: If these addresses are not tagged as VASPs, they may be")
        print("   private 'mule' wallets. The final VASP is likely 1-2 hops beyond these sinks.")

    except Exception as e:
        logger.error(f"❌ Money Trail failed: {e}", exc_info=True)

if __name__ == "__main__":
    import sys
    wallet = sys.argv[1] if len(sys.argv) > 1 else "0xeeeee90971B6264C53175D3Af6840a8dD5dc7b6C"
    asyncio.run(follow_the_money(wallet))
