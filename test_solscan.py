"""Find the correct Solscan endpoint that works with our free key."""
import asyncio
import httpx
from app.config import Settings

s = Settings()
key = s.solscan_api_key
wallet = "7YttLkHDoNj9wyDur5pM1ejNaAvT9X4eqaYcHQqtj2G5"

endpoints = [
    f"https://pro-api.solscan.io/v2.0/account/transactions?address={wallet}&page_size=5&page=1",
    f"https://api.solscan.io/v2.0/account/transactions?address={wallet}&page_size=5&page=1",
]

async def test():
    async with httpx.AsyncClient(timeout=10) as client:
        for url in endpoints:
            try:
                r = await client.get(url, headers={"token": key})
                print(f"{r.status_code} {url[:70]}")
                if r.status_code == 200:
                    d = r.json()
                    items = d.get("data", d) if isinstance(d, dict) else d
                    print(f"  -> {len(items) if isinstance(items, list) else items}")
                    break
            except Exception as e:
                print(f"Error: {e}")

asyncio.run(test())
