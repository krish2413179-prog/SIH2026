import asyncio
import uuid
import logging
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("VASP_Hunter")

async def hunt_vasp(address: str, chain: str = "ETH"):
    logger.info(f"🎯 Hunting Nearest VASP for {address} on {chain}...")

    try:
        from app.adapters.registry import get_adapter
        from app.graph.builder import build_graph
        from app.graph.vasp_finder import find_nearest_vasps
        from app.db.session import AsyncSessionLocal

        # 1. Build the graph first
        adapter = get_adapter(chain)
        logger.info("📦 Expanding graph to find VASP paths...")
        G = await build_graph(
            seed_address=address,
            chain=chain,
            adapter=adapter,
            max_hops=4,
            min_nodes=30
        )
        logger.info(f"✅ Graph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

        # 2. Use the VASP Finder (Requires DB Session)
        async with AsyncSessionLocal() as db:
            # We use a dummy trace_id and case_id for the search
            trace_id = uuid.uuid4()
            case_id = uuid.uuid4()

            logger.info("🔎 Analyzing paths to VASPs (CEX/DEX/Mixers)...")
            matches = await find_nearest_vasps(
                G=G,
                seed_address=address,
                chain=chain,
                trace_id=trace_id,
                case_id=case_id,
                db=db
            )

            if not matches:
                logger.info("❌ No VASP matches found in the current graph footprint.")
                return

            # --- RESULTS REPORT ---
            print("\n" + "═"*60)
            print(f"🚩 VASP ATTRIBUTION REPORT: {address}")
            print("═"*60)
            print(f"Nearest VASP Found: {matches[0].vasp_name}")
            print(f"VASP Address:      {matches[0].vasp_address}")
            print(f"Entity Type:       {matches[0].entity_type}")
            print(f"Distance (Hops):   {matches[0].hops}")
            print(f"Confidence:       {matches[0].confidence}")
            print(f"Value Transferred: {matches[0].total_value} ETH/Token")
            print(f"Source:            {matches[0].source}")
            print("\nPath to VASP:")
            print(" -> ".join(matches[0].path))
            print("═"*60)

            if len(matches) > 1:
                print("\nOther potential matches:")
                for i, m in enumerate(matches[1:5], 2):
                    print(f"{i}. {m.vasp_name} ({m.hops} hops, Conf: {m.confidence})")

    except Exception as e:
        logger.error(f"❌ VASP Hunter failed: {e}", exc_info=True)

if __name__ == "__main__":
    import sys
    wallet = sys.argv[1] if len(sys.argv) > 1 else "0xeeeee90971B6264C53175D3Af6840a8dD5dc7b6C"
    asyncio.run(hunt_vasp(wallet))
