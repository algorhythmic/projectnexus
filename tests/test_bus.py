"""Tests for the EventBus."""

import asyncio

import pytest

from nexus.core.types import DiscoveredMarket, EventRecord, EventType, Platform
from nexus.ingestion.bus import EventBus
from nexus.ingestion.metrics import MetricsCollector


async def _insert_market(store) -> int:
    """Insert a test market and return its id."""
    market = DiscoveredMarket(
        platform=Platform.KALSHI,
        external_id="BUS-TEST",
        title="Bus Test Market",
        yes_price=0.5,
    )
    await store.upsert_markets([market])
    stored = await store.get_market_by_external_id("kalshi", "BUS-TEST")
    return stored.id


def _make_event(market_id: int = 1, price: float = 0.5) -> EventRecord:
    """Create a test event."""
    return EventRecord(
        market_id=market_id,
        event_type=EventType.PRICE_CHANGE,
        old_value=None,
        new_value=price,
        metadata=None,
        timestamp=1000000,
    )


class TestEventBus:
    async def test_put_and_drain(self, tmp_store):
        """Events put into the bus are drained to the store."""
        mid = await _insert_market(tmp_store)
        bus = EventBus(tmp_store, max_size=100, batch_size=10, batch_timeout=0.1)
        bus.start()

        for i in range(5):
            await bus.put(_make_event(market_id=mid, price=0.5 + i * 0.01))

        # Wait for drain
        await asyncio.sleep(0.5)
        await bus.stop()

        assert bus.events_written == 5
        events = await tmp_store.get_events()
        assert len(events) == 5

    async def test_batch_flushing(self, tmp_store):
        """Events are flushed in batches up to batch_size."""
        mid = await _insert_market(tmp_store)
        bus = EventBus(tmp_store, max_size=1000, batch_size=3, batch_timeout=0.1)
        bus.start()

        for i in range(7):
            await bus.put(_make_event(market_id=mid, price=0.1 * i))

        await asyncio.sleep(0.5)
        await bus.stop()

        assert bus.events_written == 7

    async def test_stop_flushes_remaining(self, tmp_store):
        """stop() flushes any events left in the queue."""
        mid = await _insert_market(tmp_store)
        bus = EventBus(tmp_store, max_size=100, batch_size=1000, batch_timeout=10.0)
        bus.start()

        # Put events but batch_size is huge and timeout is long,
        # so they won't drain automatically before we stop
        for i in range(3):
            await bus.put(_make_event(market_id=mid, price=0.5))

        await bus.stop()
        assert bus.events_written == 3

    async def test_queue_size_tracking(self, tmp_store):
        """queue_size reflects current queue depth."""
        bus = EventBus(tmp_store, max_size=100, batch_size=1000, batch_timeout=10.0)
        # Don't start drain — just check queue size
        await bus.put(_make_event())
        await bus.put(_make_event())
        assert bus.queue_size == 2

    async def test_events_written_starts_at_zero(self, tmp_store):
        """events_written starts at zero."""
        bus = EventBus(tmp_store, max_size=100, batch_size=10, batch_timeout=0.1)
        assert bus.events_written == 0

    async def test_start_is_idempotent(self, tmp_store):
        """Calling start() twice doesn't create duplicate drain tasks."""
        bus = EventBus(tmp_store, max_size=100, batch_size=10, batch_timeout=0.1)
        bus.start()
        task1 = bus._drain_task
        bus.start()
        task2 = bus._drain_task
        assert task1 is task2
        await bus.stop()

    async def test_stop_without_start(self, tmp_store):
        """stop() on an unstarted bus does not error."""
        bus = EventBus(tmp_store, max_size=100, batch_size=10, batch_timeout=0.1)
        await bus.stop()  # should not raise

    async def test_metrics_collector_integration(self, tmp_store):
        """MetricsCollector tracks events written by the bus."""
        mid = await _insert_market(tmp_store)
        metrics = MetricsCollector()
        bus = EventBus(
            tmp_store, max_size=100, batch_size=10, batch_timeout=0.1,
            metrics=metrics,
        )
        bus.start()

        for i in range(3):
            await bus.put(_make_event(market_id=mid, price=0.5 + i * 0.01))

        await asyncio.sleep(0.5)
        await bus.stop()

        snap = metrics.snapshot()
        assert snap.total_events_written == 3
        assert bus.events_written == 3
