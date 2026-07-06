import asyncio

import pytest

from app.core.concurrency import GenerationConcurrencyLimiter
from app.core.exceptions import AppException


def test_slot_allows_up_to_max_concurrent():
    limiter = GenerationConcurrencyLimiter(max_concurrent=2, max_queue_wait_seconds=1)

    async def scenario():
        events: list[str] = []

        async def worker(name: str):
            async with limiter.slot():
                events.append(f"{name}-start")
                await asyncio.sleep(0.05)
                events.append(f"{name}-end")

        await asyncio.gather(worker("a"), worker("b"))
        return events

    events = asyncio.run(scenario())
    assert events.count("a-start") == 1
    assert events.count("b-start") == 1


def test_slot_raises_when_queue_wait_exceeded():
    limiter = GenerationConcurrencyLimiter(max_concurrent=1, max_queue_wait_seconds=0.1)

    async def scenario():
        async def hold():
            async with limiter.slot():
                await asyncio.sleep(0.5)

        holder = asyncio.create_task(hold())
        await asyncio.sleep(0.02)

        with pytest.raises(AppException) as exc_info:
            async with limiter.slot():
                pass

        holder.cancel()
        return exc_info.value

    exc = asyncio.run(scenario())
    assert exc.code == "GENERATION_BUSY"
    assert exc.status_code == 429
