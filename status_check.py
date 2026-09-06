import os, sys
os.chdir('C:/Users/kesha/sih')
from dotenv import load_dotenv
load_dotenv()
from app.config import get_settings
s = get_settings()

print("=" * 52)
print("  APP STATUS CHECK")
print("=" * 52)

# DB
try:
    from sqlalchemy import create_engine, text
    engine = create_engine(s.database_sync_url, pool_pre_ping=True)
    with engine.connect() as conn:
        tj     = conn.execute(text('SELECT COUNT(*) FROM trace_jobs')).scalar()
        cases  = conn.execute(text('SELECT COUNT(*) FROM cases')).scalar()
        users  = conn.execute(text('SELECT COUNT(*) FROM users')).scalar()
        graphs = conn.execute(text('SELECT COUNT(*) FROM trace_graphs')).scalar()
        status_counts = conn.execute(text(
            "SELECT status, COUNT(*) FROM trace_jobs GROUP BY status"
        )).fetchall()
        recent = conn.execute(text(
            "SELECT wallet_address, chain, status, risk_score, risk_band, created_at "
            "FROM trace_jobs ORDER BY created_at DESC LIMIT 5"
        )).fetchall()
    print(f"\n[DB]         OK (Supabase/PostgreSQL)")
    print(f"  cases      : {cases}")
    print(f"  users      : {users}")
    print(f"  trace_jobs : {tj}  {dict(status_counts)}")
    print(f"  graphs     : {graphs}")
    print(f"\n  Recent traces:")
    for r in recent:
        addr = r[0][:20] + '..' if len(r[0]) > 20 else r[0]
        ts = r[5].strftime('%m-%d %H:%M') if r[5] else '??'
        print(f"    [{ts}] {r[1]:<5} {addr:<24} {r[2]:<11} score={str(r[3] or '-'):<5} {r[4] or '-'}")
except Exception as e:
    print(f"\n[DB]         FAIL — {e}")

# Redis / Celery broker
try:
    import redis as rl, ssl
    r = rl.from_url(s.celery_broker_url, ssl_cert_reqs=ssl.CERT_NONE, socket_connect_timeout=5)
    pong = r.ping()
    depth = r.llen('celery')
    print(f"\n[Redis]      OK (Upstash) | queue depth={depth}")
except Exception as e:
    print(f"\n[Redis]      FAIL — {e}")

# Celery worker ping
try:
    from app.tasks.celery_app import celery_app
    resp = celery_app.control.ping(timeout=3)
    if resp:
        workers = list(resp[0].keys()) if resp else []
        print(f"[Celery]     OK | workers={workers}")
    else:
        print("[Celery]     No workers responded to ping")
except Exception as e:
    print(f"[Celery]     FAIL — {e}")

# API server
import urllib.request
for url, label in [
    ("http://localhost:8000/health", "API /health"),
    ("http://localhost:8000/docs",   "API /docs"),
    ("http://localhost:3000",        "Frontend"),
]:
    try:
        resp = urllib.request.urlopen(url, timeout=2)
        print(f"[{label:<14}] UP   (HTTP {resp.status})")
    except urllib.error.HTTPError as e:
        print(f"[{label:<14}] UP   (HTTP {e.code})")
    except Exception:
        print(f"[{label:<14}] DOWN / not reachable")

print("\n" + "=" * 52)
