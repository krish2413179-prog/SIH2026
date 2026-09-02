"""Celery application instance and configuration."""

from __future__ import annotations

from celery import Celery
from app.config import get_settings

settings = get_settings()


def _add_ssl_cert_reqs(url: str) -> str:
    """Append ssl_cert_reqs=CERT_NONE to rediss:// URLs for Upstash compatibility."""
    if url.startswith("rediss://") and "ssl_cert_reqs" not in url:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}ssl_cert_reqs=CERT_NONE"
    return url


import ssl

broker_url = _add_ssl_cert_reqs(settings.celery_broker_url)
result_backend = _add_ssl_cert_reqs(settings.celery_result_backend)

celery_app = Celery(
    "vasp_engine",
    broker=broker_url,
    backend=result_backend,
    include=[
        "app.tasks.trace_tasks",
        "app.tasks.sahyog_tasks",
    ],
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Queue routing
    task_routes={
        "tasks.trace.*": {"queue": "traces"},
        "tasks.report.*": {"queue": "reports"},
        "tasks.sahyog.*": {"queue": "sahyog"},
    },
    # Worker settings
    worker_concurrency=8,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    # Disable result storage to avoid Upstash DB-1 issues
    task_ignore_result=True,
    result_expires=86400,
    # Retry settings
    task_max_retries=3,
    # Beat schedule
    beat_schedule={},
    # Redis SSL config for Upstash
    broker_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
    redis_backend_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
    # Suppress Celery 6.0 deprecation warning
    broker_connection_retry_on_startup=True,
)
