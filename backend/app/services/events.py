"""Simple in-process event bus for SSE notifications."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

# In-memory event buffer (latest 100 events)
_event_buffer: deque[dict[str, Any]] = deque(maxlen=100)
_listeners: list[asyncio.Queue[dict[str, Any]]] = []


def publish_event(event_type: str, data: dict[str, Any] | None = None) -> None:
    """Publish an event to all connected SSE listeners."""
    event = {
        "type": event_type,
        "data": data or {},
        "timestamp": time.time(),
    }
    _event_buffer.append(event)
    for queue in _listeners:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass  # Drop events for slow consumers
    logger.debug("Published event: %s", event_type)


async def event_stream() -> AsyncIterator[str]:
    """Async generator that yields SSE-formatted events."""
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=50)
    _listeners.append(queue)
    try:
        # Send recent events as initial batch
        for event in _event_buffer:
            yield f"data: {json.dumps(event)}\n\n"

        # Stream new events
        while True:
            event = await queue.get()
            yield f"data: {json.dumps(event)}\n\n"
    finally:
        _listeners.remove(queue)
