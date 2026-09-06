"""Test script: create a TraceJob in DB and dispatch it via Celery."""
import sys, uuid, time
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from app.config import get_settings

settings = get_settings()

# ── DB connection ────────────────────────────────────────────────────────────
engine = create_engine(settings.database_sync_url, pool_pre_ping=True)
Session = sessionmaker(bind=engine)

# ── Pick a case to attach to ─────────────────────────────────────────────────
with Session() as db:
    row = db.execute(text("SELECT id FROM cases LIMIT 1")).fetchone()
    if row is None:
        print("ERROR: no cases in DB — create a case first")
        sys.exit(1)
    case_id = row[0]
    print(f"Using case_id: {case_id}")

# ── Create a TraceJob ─────────────────────────────────────────────────────────
from app.graph.models import TraceJob

TEST_WALLET = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"  # Vitalik's public address
TEST_CHAIN  = "ETH"

job_id = uuid.uuid4()
with Session() as db:
    job = TraceJob(
        id=job_id,
        case_id=case_id,
        wallet_address=TEST_WALLET,
        chain=TEST_CHAIN,
        status="queued",
        max_hops=2,
    )
    db.add(job)
    db.commit()
    print(f"Created TraceJob: {job_id}")
    print(f"  wallet : {TEST_WALLET}")
    print(f"  chain  : {TEST_CHAIN}")

# ── Dispatch Celery task ───────────────────────────────────────────────────────
from app.tasks.trace_tasks import run_trace

result = run_trace.delay(str(job_id))
print(f"\nDispatched task — Celery task_id: {result.id}")
print("Polling for completion (max 120s)...")

# ── Poll DB for status ─────────────────────────────────────────────────────────
for i in range(24):
    time.sleep(5)
    with Session() as db:
        j = db.execute(select(TraceJob).where(TraceJob.id == job_id)).scalars().first()
        status = j.status if j else "unknown"
        pct    = getattr(j, "estimated_pct", None)
        risk   = getattr(j, "risk_score", None)
        band   = getattr(j, "risk_band", None)
    elapsed = (i + 1) * 5
    print(f"  [{elapsed:3d}s] status={status}  pct={pct}  risk={risk}  band={band}")
    if status in ("completed", "failed"):
        break

print("\n─── FINAL RESULT ───")
with Session() as db:
    j = db.execute(select(TraceJob).where(TraceJob.id == job_id)).scalars().first()
    if j:
        print(f"  status     : {j.status}")
        print(f"  risk_score : {getattr(j, 'risk_score', 'N/A')}")
        print(f"  risk_band  : {getattr(j, 'risk_band', 'N/A')}")
        print(f"  started_at : {getattr(j, 'started_at', 'N/A')}")
        print(f"  completed_at: {getattr(j, 'completed_at', 'N/A')}")
    else:
        print("  Job not found in DB!")
