"""Event bus for routing normalized events to the store.

Uses a bounded asyncio.Queue for backpressure: when the store can't keep
up with incoming events, the queue fills and producers block on put(),
propagating TCP backpressure to the WebSocket connection.

Events are drained in batches for efficient bulk inserts.
"""

import asyncio
from typing import List, Optional

from nexus.core.logging import LoggerMixin
from nexus.core.types import EventRecord
from nexus.store.base import BaseStore


class EventBus(LoggerMixin):
    """Bounded event queue with batch drain worker.

    Usage::

        bus = EventBus(store, max_size=10_000)
        bus.start()
        await bus.put(event)   # blocks when queue is full
        ...
        await bus.stop()       # flushes remaining events
    """

    def __init__(
        self,
        store: BaseStore,
        max_size: int = 10_000,
        batch_size: int = 100,
        batch_timeout: float = 1.0,
    ) -> None:
        self._store = store
        self._queue: asyncio.Queue[EventRecord] = asyncio.Queue(maxsize=max_size)
        self._batch_size = batch_size
        self._batch_timeout = batch_timeout
        self._drain_task: Optional[asyncio.Task[None]] = None
        self._shutdown = asyncio.Event()
        self._events_written = 0

    @property
    def events_written(self) -> int:
        """Total events successfully written to the store."""
        return self._events_written

    @property
    def queue_size(self) -> int:
        """Current number of events waiting in the queue."""
        return self._queue.qsize()

    def start(self) -> None:
        """Launch the background drain worker."""
        if self._drain_task is not None:
            return
        self._shutdown.clear()
        self._drain_task = asyncio.get_event_loop().create_task(self._drain_loop())
        self.logger.info(
            "EventBus started",
            max_size=self._queue.maxsize,
            batch_size=self._batch_size,
        )

    async def stop(self) -> None:
        """Signal shutdown, flush remaining events, cancel drain task."""
        self._shutdown.set()
        if self._drain_task is not None:
            try:
                await asyncio.wait_for(self._drain_task, timeout=10.0)
            except asyncio.TimeoutError:
                self._drain_task.cancel()
                try:
                    await self._drain_task
                except asyncio.CancelledError:
                    pass
            self._drain_task = None
        # Final flush of anything left in the queue
        await self._flush_remaining()
        self.logger.info(
            "EventBus stopped", total_events_written=self._events_written
        )

    async def put(self, event: EventRecord) -> None:
        """Enqueue an event. Blocks if the queue is full (backpressure)."""
        await self._queue.put(event)

    # ------------------------------------------------------------------
    # Internal drain worker
    # ------------------------------------------------------------------

    async def _drain_loop(self) -> None:
        """Continuously drain events from the queue in batches."""
        while not self._shutdown.is_set():
            batch = await self._collect_batch()
            if batch:
                await self._write_batch(batch)

    async def _collect_batch(self) -> List[EventRecord]:
        """Collect up to batch_size events, waiting at most batch_timeout."""
        batch: List[EventRecord] = []

        # Block until at least one event is available or shutdown
        try:
            event = await asyncio.wait_for(
                self._queue.get(), timeout=self._batch_timeout
            )
            batch.append(event)
        except asyncio.TimeoutError:
            return batch

        # Grab more without waiting, up to batch_size
        while len(batch) < self._batch_size:
            try:
                event = self._queue.get_nowait()
                batch.append(event)
            except asyncio.QueueEmpty:
                break

        return batch

    async def _write_batch(self, batch: List[EventRecord]) -> None:
        """Write a batch of events to the store."""
        try:
            count = await self._store.insert_events(batch)
            self._events_written += count
            self.logger.debug(
                "Batch written",
                batch_size=len(batch),
                total_written=self._events_written,
                queue_remaining=self._queue.qsize(),
            )
        except Exception as exc:
            self.logger.error(
                "Failed to write event batch",
                batch_size=len(batch),
                error=str(exc),
            )

    async def _flush_remaining(self) -> None:
        """Drain any events left in the queue after shutdown signal."""
        remaining: List[EventRecord] = []
        while not self._queue.empty():
            try:
                remaining.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if remaining:
            await self._write_batch(remaining)
            self.logger.info(
                "Flushed remaining events", count=len(remaining)
            )
