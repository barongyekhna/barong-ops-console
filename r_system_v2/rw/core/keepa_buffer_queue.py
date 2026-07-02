"""Buffered Keepa result queue for high-concurrency ingestion."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from r_system_v2.rw.core.models import PipelineResult


DEFAULT_BATCH_SIZE = 250
MIN_BATCH_SIZE = 100
MAX_BATCH_SIZE = 500
DEFAULT_FLUSH_INTERVAL_SECONDS = 5.0
MIN_FLUSH_INTERVAL_SECONDS = 5.0
MAX_FLUSH_INTERVAL_SECONDS = 10.0

BatchWriterCallback = Callable[[Sequence[PipelineResult]], Any | Awaitable[Any]]


@dataclass(frozen=True)
class KeepaBufferStats:
    batch_size: int
    flush_interval_seconds: float
    pending: int
    total_enqueued: int
    total_flushed: int
    flush_count: int
    last_flush_size: int
    max_observed_batch_size: int

    @property
    def active(self) -> bool:
        return MIN_BATCH_SIZE <= self.batch_size <= MAX_BATCH_SIZE

    def to_dict(self) -> dict[str, int | float | bool]:
        return {
            "batch_size": self.batch_size,
            "flush_interval_seconds": self.flush_interval_seconds,
            "pending": self.pending,
            "total_enqueued": self.total_enqueued,
            "total_flushed": self.total_flushed,
            "flush_count": self.flush_count,
            "last_flush_size": self.last_flush_size,
            "max_observed_batch_size": self.max_observed_batch_size,
            "active": self.active,
        }


class KeepaBufferQueue:
    """Accumulates Keepa pipeline results and flushes them in DB-sized batches."""

    def __init__(
        self,
        writer: BatchWriterCallback | None = None,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        flush_interval_seconds: float = DEFAULT_FLUSH_INTERVAL_SECONDS,
    ) -> None:
        if not MIN_BATCH_SIZE <= batch_size <= MAX_BATCH_SIZE:
            raise ValueError("Keepa batch_size must be between 100 and 500")
        if not MIN_FLUSH_INTERVAL_SECONDS <= flush_interval_seconds <= MAX_FLUSH_INTERVAL_SECONDS:
            raise ValueError("Keepa flush interval must be between 5 and 10 seconds")
        self.writer = writer
        self.batch_size = batch_size
        self.flush_interval_seconds = flush_interval_seconds
        self._items: list[PipelineResult] = []
        self._lock = asyncio.Lock()
        self._last_flush_at = time.monotonic()
        self._total_enqueued = 0
        self._total_flushed = 0
        self._flush_count = 0
        self._last_flush_size = 0
        self._max_observed_batch_size = 0

    async def put(self, item: PipelineResult) -> None:
        batch: list[PipelineResult] = []
        async with self._lock:
            self._items.append(item)
            self._total_enqueued += 1
            if len(self._items) >= self.batch_size:
                batch = self._drain_locked(self.batch_size)
        if batch:
            await self._write_batch(batch)

    async def put_many(self, items: Sequence[PipelineResult]) -> None:
        for item in items:
            await self.put(item)

    async def flush_due(self) -> int:
        batch: list[PipelineResult] = []
        async with self._lock:
            if self._items and time.monotonic() - self._last_flush_at >= self.flush_interval_seconds:
                batch = self._drain_locked()
        if not batch:
            return 0
        await self._write_batch(batch)
        return len(batch)

    async def flush(self) -> int:
        async with self._lock:
            batch = self._drain_locked()
        if not batch:
            return 0
        await self._write_batch(batch)
        return len(batch)

    async def run_flush_loop(self, stop_event: asyncio.Event | None = None) -> None:
        while stop_event is None or not stop_event.is_set():
            await asyncio.sleep(self.flush_interval_seconds)
            await self.flush()

    def stats(self) -> KeepaBufferStats:
        return KeepaBufferStats(
            batch_size=self.batch_size,
            flush_interval_seconds=self.flush_interval_seconds,
            pending=len(self._items),
            total_enqueued=self._total_enqueued,
            total_flushed=self._total_flushed,
            flush_count=self._flush_count,
            last_flush_size=self._last_flush_size,
            max_observed_batch_size=self._max_observed_batch_size,
        )

    def _drain_locked(self, limit: int | None = None) -> list[PipelineResult]:
        if limit is None:
            batch = list(self._items)
            self._items.clear()
        else:
            batch = self._items[:limit]
            del self._items[:limit]
        if batch:
            self._last_flush_at = time.monotonic()
        return batch

    async def _write_batch(self, batch: Sequence[PipelineResult]) -> None:
        if not batch:
            return
        self._last_flush_size = len(batch)
        self._max_observed_batch_size = max(self._max_observed_batch_size, len(batch))
        if self.writer is not None:
            result = self.writer(batch)
            if inspect.isawaitable(result):
                await result
        self._total_flushed += len(batch)
        self._flush_count += 1
