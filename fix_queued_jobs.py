# -*- coding: utf-8 -*-
import os, sys
os.chdir('C:/Users/kesha/sih')
from dotenv import load_dotenv
load_dotenv()
from app.config import get_settings
s = get_settings()
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

engine = create_engine(s.database_sync_url)
Session = sessionmaker(bind=engine)

# 1. Mark stuck 'running' jobs as failed
print("Step 1: Fix stuck running jobs")
with Session() as db:
    result = db.execute(text("""
        UPDATE trace_jobs
        SET status = 'failed', completed_at = NOW()
        WHERE status = 'running'
        AND started_at < NOW() - INTERVAL '30 minutes'
        RETURNING id, wallet_address, chain
    """))
    db.commit()
    fixed = result.fetchall()
    if fixed:
        for f in fixed:
            print("  FIXED stuck: %s %s -> failed  [%s]" % (f[2], f[1], f[0]))
    else:
        print("  None found")

# 2. Cancel duplicate queued jobs (same wallet+chain, keep newest)
print("Step 2: Cancel duplicate queued jobs")
with Session() as db:
    dupes = db.execute(text("""
        WITH ranked AS (
            SELECT id, wallet_address, chain,
                   ROW_NUMBER() OVER (
                       PARTITION BY wallet_address, chain
                       ORDER BY enqueued_at DESC
                   ) AS rn
            FROM trace_jobs WHERE status = 'queued'
        )
        SELECT id, wallet_address, chain FROM ranked WHERE rn > 1
    """)).fetchall()

    if dupes:
        ids_str = "', '".join(str(r[0]) for r in dupes)
        db.execute(text("UPDATE trace_jobs SET status = 'cancelled' WHERE id IN ('%s')" % ids_str))
        db.commit()
        for d in dupes:
            print("  CANCELLED: %s %s [%s]" % (d[2], str(d[1])[:32], d[0]))
        print("  Total cancelled: %d" % len(dupes))
    else:
        print("  No duplicates found")

# 3. Dispatch remaining unique queued jobs
print("Step 3: Dispatch remaining queued jobs to Celery")
from app.tasks.trace_tasks import run_trace

with Session() as db:
    jobs = db.execute(text("""
        SELECT id, wallet_address, chain FROM trace_jobs
        WHERE status = 'queued'
        ORDER BY enqueued_at ASC
    """)).fetchall()

    if not jobs:
        print("  No queued jobs remaining")
        sys.exit(0)

    dispatched = 0
    for job in jobs:
        job_id = str(job[0])
        task = run_trace.delay(job_id)
        db.execute(text(
            "UPDATE trace_jobs SET celery_task_id = :tid WHERE id = CAST(:jid AS uuid)"
        ), {'tid': task.id, 'jid': job_id})
        print("  [%d] %s  %s  task=%s..." % (dispatched + 1, str(job[2]).ljust(5), str(job[1])[:32], task.id[:8]))
        dispatched += 1
    db.commit()
    print("  Total dispatched: %d" % dispatched)

print("Done.")
