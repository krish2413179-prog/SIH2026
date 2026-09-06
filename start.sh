#!/usr/bin/env bash
set -e

echo "[START] Launching Celery background worker..."
celery -A app.tasks.celery_app.celery_app worker \
  -Q celery,traces,reports,sahyog \
  -n render-worker \
  --loglevel=info \
  --concurrency=2 &

echo "[START] Launching FastAPI Web Server on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
