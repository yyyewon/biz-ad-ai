"""
생성 요청 동시성 제어 모듈
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from time import perf_counter

from loguru import logger

from app.core.exceptions import AppException


class GenerationConcurrencyLimiter:
    def __init__(self, max_concurrent: int = 2, max_queue_wait_seconds: float = 15.0):
        if max_concurrent < 1:
            raise ValueError("max_concurrent는 1 이상이어야 합니다.")
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._max_queue_wait_seconds = max_queue_wait_seconds
        self._waiting = 0

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    @asynccontextmanager
    async def slot(self):
        """
        생성 작업 실행 전 슬롯을 확보하는 컨텍스트 매니저입니다.

        사용 예:
            async with generation_limiter.slot():
                ... 실제 생성 로직 ...
        """
        self._waiting += 1
        start = perf_counter()
        try:
            try:
                await asyncio.wait_for(
                    self._semaphore.acquire(),
                    timeout=self._max_queue_wait_seconds,
                )
            except asyncio.TimeoutError as exc:
                waited_ms = round((perf_counter() - start) * 1000, 2)
                logger.warning(
                    "generation_queue_timeout | waited_ms={} | waiting_count={} | max_concurrent={}",
                    waited_ms,
                    self._waiting,
                    self._max_concurrent,
                )
                raise AppException(
                    code="GENERATION_BUSY",
                    message="현재 생성 요청이 많아 처리할 수 없어요. 잠시 후 다시 시도해 주세요.",
                    status_code=429,
                    detail={"max_concurrent": self._max_concurrent},
                ) from exc
        finally:
            self._waiting -= 1

        acquired_at = perf_counter()
        try:
            yield
        finally:
            elapsed_ms = round((perf_counter() - acquired_at) * 1000, 2)
            logger.info("generation_slot_released | elapsed_ms={}", elapsed_ms)
            self._semaphore.release()


generation_limiter = GenerationConcurrencyLimiter(
    max_concurrent=int(os.getenv("GENERATION_MAX_CONCURRENT", "2")),
    max_queue_wait_seconds=float(os.getenv("GENERATION_QUEUE_TIMEOUT_SECONDS", "15")),
)
