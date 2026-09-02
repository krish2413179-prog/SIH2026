import asyncio
from app.adapters.bscscan import BscScanAdapter
from app.adapters.polygonscan import PolygonscanAdapter
from app.adapters.solscan import SolscanAdapter

async def test_all():
    # BSC - Binance hot wallet (very active)
    bsc = BscScanAdapter()
    txs = await bsc.get_transactions('0xF977814e90dA44bFA03b6295A0616a897441aceC', page=1, page_size=5)
    print(f'BSC: {len(txs)} transactions')
    if txs:
        t = txs[0]
        print(f'  Sample: {t.tx_hash[:16]}... {float(t.amount):.4f} BNB')

    # Polygon
    poly = PolygonscanAdapter()
    txs = await poly.get_transactions('0x742d35Cc6634C0532925a3b844Bc454e4438f44e', page=1, page_size=5)
    print(f'Polygon: {len(txs)} transactions')

    # Solana V2 
    sol = SolscanAdapter()
    txs = await sol.get_transactions('7YttLkHDoNj9wyDur5pM1ejNaAvT9X4eqaYcHQqtj2G5', page=1, page_size=5)
    print(f'Solana: {len(txs)} transactions')

asyncio.run(test_all())
