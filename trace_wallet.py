import asyncio
import os
import logging
from dotenv import load_dotenv
import networkx as nx

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("WalletTrace")

async def trace_wallet(address: str, chain: str = "ETH"):
    logger.info(f"🔍 Initiating Forensic Trace for {address} on {chain}...")

    try:
        from app.adapters.registry import get_adapter
        from app.graph.builder import build_graph
        from app.graph.sweep_detector import detect_deposit_sweeps
        from app.ml.detector import get_detector
        from app.risk.scorer import compute_risk_score, classify_risk_band

        # 1. Initialize Adapter
        adapter = get_adapter(chain)

        # 2. Build Graph (BFS)
        logger.info("📦 Building transaction graph (BFS expansion)...")
        G = await build_graph(
            seed_address=address,
            chain=chain,
            adapter=adapter,
            max_hops=3,
            min_nodes=15
        )
        logger.info(f"✅ Graph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

        # 3. Deterministic Attribution (Sweep Detection)
        # For the demo, we simulate the known_hot_wallets db lookup
        # In production, this comes from the VASP database.
        # We'll use a few common hot wallets for the demo.
        known_hot_wallets = {
            "0x0000000000000000000000000000000000000000": "System/Burn",
        }
        # In a real scenario, we'd fetch these from the DB.
        sweep_results = detect_deposit_sweeps(G, known_hot_wallets)

        # 4. ML Suspicion Analysis
        logger.info("🤖 Running ML Suspicion Detector...")
        detector = get_detector()

        # We need transactions for the seed address to run the ML detector
        # The adapter can provide these.
        txs = await adapter.get_transactions(address)
        ml_res = detector.predict_wallet(address, txs, chain=chain)

        # 5. Calculate Final Risk Score
        # Using the weighted formula
        # Direct exposure: ratio of flagged nodes in G
        flagged_nodes = sum(1 for _, attrs in G.nodes(data=True)
                           if attrs.get("entity_type") in ("sanctioned", "mixer", "darknet", "flagged"))
        direct_exp = min(1.0, flagged_nodes / (G.number_of_nodes() or 1))

        risk_score = compute_risk_score(
            direct_exposure=direct_exp,
            indirect_exposure=direct_exp * 0.5,
            vasp_risk_category=0.2, # Default
            typology_flags=0.5 if ml_res['is_suspicious'] else 0.1,
            volume_anomaly=0.3
        )
        risk_band = classify_risk_band(risk_score)

        # --- FORENSIC REPORT ---
        print("\n" + "="*60)
        print(f"FORENSIC DOSSIER: {address}")
        print("="*60)
        print(f"Chain:            {chain}")
        print(f"Nodes Discovered: {G.number_of_nodes()}")
        print(f"Edges Discovered: {G.number_of_edges()}")
        print(f"Suspicion Score:  {ml_res['suspicion_score']}/100")
        print(f"Risk Band:        {risk_band.upper()} (Score: {risk_score})")
        print(f"ML Analysis:      {'SUSPICIOUS' if ml_res['is_suspicious'] else 'BENIGN'}")
        print(f"Detected Patterns: {', '.join(ml_res['detected_patterns']) if ml_res['detected_patterns'] else 'None'}")

        if sweep_results:
            print("\n⚠️  VASP ATTRIBUTION DETECTED:")
            for addr, res in sweep_results.items():
                print(f" - {addr} is a deposit address for {res.parent_exchange}")
                print(f"   Confidence: {res.confidence} | Sweep Ratio: {res.sweep_ratio}")
        else:
            print("\nℹ️  No deterministic VASP attribution found.")

        print("="*60)

    except Exception as e:
        logger.error(f"❌ Trace failed: {e}", exc_info=True)

if __name__ == "__main__":
    import sys
    wallet = sys.argv[1] if len(sys.argv) > 1 else "0xCb188D3DBAb64D9B01c6B49193F76d762a00f268"
    asyncio.run(trace_wallet(wallet))
