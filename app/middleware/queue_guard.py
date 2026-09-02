"""Queue depth guard middleware.

Returns HTTP 429 Too Many Requests when the Celery ``traces`` queue depth
exceeds the configured limit (default: 100 jobs).

Only applies to POST requests on ``/*/wallets`` paths — the entry point for
new trace jobs.  All other requests pass through unchanged.

Requirements: 18.2, 15.4
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# Redis key used by Celery for the traces queue (list-based broker)
_TRACES_QUEUE_KEY = "traces"

# URL pattern suffix that triggers the queue depth check
_WALLETS_PATH_SUFFIX = "/wallets"


class QueueDepthGuardMiddleware(BaseHTTPMiddleware):
    """Reject wallet-submission POSTs when the trace queue is too deep.

    Configuration is read from ``app.config.Settings`` at first use so that
    test overrides applied after import are respected.

    Behaviour:
    - Only intercepts ``POST`` requests whose path ends with ``/wallets``.
    - Reads the ``traces`` Redis list length via ``LLEN``.
    - If depth > ``trace_queue_depth_limit`` (default 100): returns
      ``HTTP 429`` with a ``Retry-After: 60`` header and a JSON error body.
    - On any Redis error: logs the exception and allows the request through
      (fail-open to avoid blocking legitimate submissions when Redis is
      temporarily unavailable).

    Requirements: 18.2, 15.4
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Fast-path: only check POST requests to wallet submission endpoints
        if request.method.upper() != "POST" or not request.url.path.endswith(
            _WALLETS_PATH_SUFFIX
        ):
            return await call_next(request)

        try:
            depth = await self._get_queue_depth()
            limit = self._get_limit()

            if depth > limit:
                logger.warning(
                    "queue_depth_guard: traces queue depth %d exceeds limit %d "
                    "— returning HTTP 429 for %s",
                    depth,
                    limit,
                    request.url.path,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": (
                            f"Trace queue is currently full ({depth} jobs queued). "
                            "Please retry after a short delay."
                        ),
                        "queue_depth": depth,
                        "queue_limit": limit,
                    },
                    headers={"Retry-After": "60"},
                )
        except Exception:
            # Fail-open: log but do not block the request
            logger.exception(
                "queue_depth_guard: failed to read queue depth — allowing request through"
            )

        return await call_next(request)

    @staticmethod
    async def _get_queue_depth() -> int:
        """Return the current length of the Celery traces queue in Redis."""
        from app.cache.redis import get_redis_client

        redis = get_redis_client()
        depth = await redis.llen(_TRACES_QUEUE_KEY)
        return int(depth)

    @staticmethod
    def _get_limit() -> int:
        """Return the configured queue depth limit."""
        from app.config import get_settings

        return get_settings().trace_queue_depth_limit
