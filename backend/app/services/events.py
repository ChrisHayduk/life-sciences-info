"""Simple in-process event bus for SSE notifications."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import deque
from typing import Any, AsyncIterator

from starlette.requests import Request

logger = logging.getLogger(__name__)

# In-memory event buffer (latest 100 events)
_event_buffer: deque[dict[str, Any]] = deque(maxlen=100)
_listeners: list[tuple[asyncio.Queue[dict[str, Any]], float]] = []
HEARTBEAT_INTERVAL_SECONDS = 15.0
MAX_SSE_LISTENERS = 50
LISTENER_TTL_SECONDS = 3600.0  # 1 hour


def _format_sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _prune_stale_listeners() -> None:
    """Remove listeners older than LISTENER_TTL_SECONDS."""
    cutoff = time.monotonic() - LISTENER_TTL_SECONDS
    stale = [entry for entry in _listeners if entry[1] < cutoff]
    for entry in stale:
        with contextlib.suppress(ValueError):
            _listeners.remove(entry)
    if stale:
        logger.info("Pruned %d stale SSE listeners; %d remain", len(stale), len(_listeners))


def listener_count() -> int:
    return len(_listeners)


def reset_event_state() -> None:
    _event_buffer.clear()
    _listeners.clear()


def publish_event(event_type: str, data: dict[str, Any] | None = None) -> None:
    """Publish an event to all connected SSE listeners."""
    event = {
        "type": event_type,
        "data": data or {},
        "timestamp": time.time(),
    }
    _event_buffer.append(event)
    for queue, _created_at in tuple(_listeners):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass  # Drop events for slow consumers
    logger.debug("Published event: %s", event_type)


async def event_stream(
    request: Request,
    *,
    heartbeat_interval: float = HEARTBEAT_INTERVAL_SECONDS,
) -> AsyncIterator[str]:
    """Async generator that yields SSE-formatted events."""
    _prune_stale_listeners()

    if len(_listeners) >= MAX_SSE_LISTENERS:
        logger.warning("SSE listener cap reached (%d); rejecting new connection", MAX_SSE_LISTENERS)
        yield _format_sse({"type": "error", "data": {"message": "Too many listeners"}, "timestamp": time.time()})
        return

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=50)
    entry = (queue, time.monotonic())
    _listeners.append(entry)
    logger.debug("SSE listener connected; %s active listeners", len(_listeners))
    try:
        # Send recent events as initial batch
        for event in tuple(_event_buffer):
            yield _format_sse(event)

        # Stream new events
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
            except asyncio.TimeoutError:
                if await request.is_disconnected():
                    break
                yield ": keepalive\n\n"
                continue
            yield _format_sse(event)
    finally:
        with contextlib.suppress(ValueError):
            _listeners.remove(entry)
        logger.debug("SSE listener disconnected; %s active listeners", len(_listeners))
