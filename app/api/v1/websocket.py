"""WebSocket notification handler.

Provides a per-user notification channel backed by Redis pub/sub, plus a
broadcast channel for system-wide risk alerts.

Channels:
  - ``notifications:{user_id}``  — targeted user notifications
  - ``risk_alerts_broadcast``    — system-wide risk alerts broadcast to all
                                   connected clients

Requirements: 18.6
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# Redis channel for system-wide broadcasts
_BROADCAST_CHANNEL = "risk_alerts_broadcast"


@router.websocket("/ws/notifications/{user_id}")
async def notifications_ws(websocket: WebSocket, user_id: str) -> None:
    """Subscribe to per-user and broadcast Redis pub/sub channels.

    On connection:
    1. Accept the WebSocket upgrade.
    2. Subscribe to ``notifications:{user_id}`` (targeted) and
       ``risk_alerts_broadcast`` (system-wide).
    3. Forward any published JSON message to the connected client.
    4. On ``WebSocketDisconnect`` or client closure: unsubscribe and clean up.

    The connection remains open indefinitely until the client disconnects or
    a Redis error terminates the subscription.

    Args:
        websocket: The WebSocket connection managed by FastAPI/Starlette.
        user_id:   The user identifier embedded in the URL path.  Used to
                   construct the per-user channel name.

    Requirements: 18.6
    """
    await websocket.accept()
    logger.info("WebSocket connected: user_id=%s", user_id)

    user_channel = f"notifications:{user_id}"

    try:
        from app.cache.redis import get_redis_client
        import redis.asyncio as aioredis

        redis_client = get_redis_client()
        # Create a dedicated pub/sub connection
        pubsub: aioredis.client.PubSub = redis_client.pubsub()

        await pubsub.subscribe(user_channel, _BROADCAST_CHANNEL)
        logger.debug(
            "WebSocket subscribed to channels: %s, %s",
            user_channel,
            _BROADCAST_CHANNEL,
        )

        try:
            while True:
                # Use a timeout so we can periodically check connection health
                try:
                    message = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    # No message yet — send a keepalive ping and continue
                    try:
                        await websocket.send_json({"type": "ping"})
                    except Exception:
                        # Client disconnected during ping
                        break
                    continue

                if message is None:
                    # Brief sleep to avoid a tight busy-loop
                    await asyncio.sleep(0.1)
                    continue

                # Decode and forward the message payload
                raw_data = message.get("data")
                if raw_data is None:
                    continue

                if isinstance(raw_data, bytes):
                    raw_data = raw_data.decode("utf-8", errors="replace")

                # Attempt to parse as JSON; fall back to plain string wrapper
                try:
                    payload = json.loads(raw_data)
                except (json.JSONDecodeError, TypeError):
                    payload = {"type": "notification", "data": raw_data}

                # Inject channel metadata for client routing
                payload.setdefault("channel", message.get("channel", "").decode(
                    "utf-8", errors="replace"
                ) if isinstance(message.get("channel"), bytes) else message.get("channel", ""))

                try:
                    await websocket.send_json(payload)
                except Exception:
                    # Client disconnected while we were sending
                    break

        finally:
            await pubsub.unsubscribe(user_channel, _BROADCAST_CHANNEL)
            await pubsub.close()
            logger.debug(
                "WebSocket unsubscribed and pubsub closed for user_id=%s", user_id
            )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: user_id=%s", user_id)
    except Exception:
        logger.exception(
            "WebSocket error for user_id=%s — closing connection", user_id
        )
        try:
            await websocket.close(code=1011)  # Internal error
        except Exception:
            pass
    finally:
        logger.info("WebSocket session ended: user_id=%s", user_id)
