from __future__ import annotations

import asyncio

from app.services.events import event_stream, listener_count, publish_event, reset_event_state


class FakeRequest:
    def __init__(self, disconnected_states: list[bool] | None = None) -> None:
        self._states = list(disconnected_states or [])

    async def is_disconnected(self) -> bool:
        if self._states:
            return self._states.pop(0)
        return False


def test_event_stream_removes_listener_after_disconnect() -> None:
    reset_event_state()

    async def consume() -> None:
        async for _ in event_stream(FakeRequest([False, True]), heartbeat_interval=0.001):
            pass

    asyncio.run(consume())

    assert listener_count() == 0


def test_event_stream_yields_buffered_and_live_events() -> None:
    reset_event_state()
    publish_event("new_filing", {"title": "Buffered"})

    async def consume() -> tuple[str, str]:
        generator = event_stream(FakeRequest(), heartbeat_interval=0.05)
        first = await anext(generator)
        publish_event("new_news", {"title": "Live"})
        second = await anext(generator)
        await generator.aclose()
        return first, second

    first, second = asyncio.run(consume())

    assert '"type": "new_filing"' in first
    assert '"title": "Buffered"' in first
    assert '"type": "new_news"' in second
    assert '"title": "Live"' in second
    assert listener_count() == 0
