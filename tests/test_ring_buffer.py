"""Tests for EventRingBuffer."""

import time

import pytest

from nexus.core.types import EventRecord, EventType
from nexus.ingestion.ring_buffer import EventRingBuffer


def _make_event(
    market_id: int = 1,
    event_type: EventType = EventType.PRICE_CHANGE,
    timestamp: int | None = None,
    new_value: float = 0.65,
) -> EventRecord:
    """Helper to create test events."""
    return EventRecord(
        market_id=market_id,
        event_type=event_type,
        timestamp=timestamp or int(time.time() * 1000),
        new_value=new_value,
    )


class TestEventRingBuffer:
    def test_add_and_retrieve(self):
        buf = EventRingBuffer(max_age_seconds=3600)
        event = _make_event(market_id=1)
        buf.add(event)

        events = buf.get_events(1)
        assert len(events) == 1
        assert events[0] is event

    def test_empty_market_returns_empty(self):
        buf = EventRingBuffer()
        assert buf.get_events(999) == []

    def test_since_ts_filter(self):
        buf = EventRingBuffer()
        now = int(time.time() * 1000)

        old_event = _make_event(timestamp=now - 60000)  # 60s ago
        new_event = _make_event(timestamp=now)

        buf.add(old_event)
        buf.add(new_event)

        # Only get events from last 30 seconds
        events = buf.get_events(1, since_ts=now - 30000)
        assert len(events) == 1
        assert events[0] is new_event

    def test_event_type_filter(self):
        buf = EventRingBuffer()
        price = _make_event(event_type=EventType.PRICE_CHANGE)
        trade = _make_event(event_type=EventType.TRADE)

        buf.add(price)
        buf.add(trade)

        events = buf.get_events(1, event_type=EventType.TRADE)
        assert len(events) == 1
        assert events[0].event_type == EventType.TRADE

    def test_combined_filters(self):
        buf = EventRingBuffer()
        now = int(time.time() * 1000)

        old_trade = _make_event(event_type=EventType.TRADE, timestamp=now - 60000)
        new_price = _make_event(event_type=EventType.PRICE_CHANGE, timestamp=now)
        new_trade = _make_event(event_type=EventType.TRADE, timestamp=now)

        buf.add(old_trade)
        buf.add(new_price)
        buf.add(new_trade)

        events = buf.get_events(1, since_ts=now - 30000, event_type=EventType.TRADE)
        assert len(events) == 1
        assert events[0] is new_trade

    def test_max_events_per_market(self):
        buf = EventRingBuffer(max_events_per_market=5)
        now = int(time.time() * 1000)

        for i in range(10):
            buf.add(_make_event(timestamp=now + i))

        events = buf.get_events(1)
        assert len(events) == 5
        # Should have the newest 5
        assert events[0].timestamp == now + 5

    def test_cleanup_expired(self):
        buf = EventRingBuffer(max_age_seconds=60)
        now = int(time.time() * 1000)

        old = _make_event(timestamp=now - 120000)  # 2 min ago (expired)
        recent = _make_event(timestamp=now)

        buf.add(old)
        buf.add(recent)

        removed = buf.cleanup_expired()
        assert removed == 1
        assert len(buf.get_events(1)) == 1

    def test_cleanup_removes_empty_markets(self):
        buf = EventRingBuffer(max_age_seconds=60)
        now = int(time.time() * 1000)

        old = _make_event(market_id=99, timestamp=now - 120000)
        buf.add(old)
        assert 99 in buf._buffers

        buf.cleanup_expired()
        assert 99 not in buf._buffers

    def test_maybe_cleanup_respects_interval(self):
        buf = EventRingBuffer(max_age_seconds=60, cleanup_interval_seconds=600)
        now = int(time.time() * 1000)

        old = _make_event(timestamp=now - 120000)
        buf.add(old)

        # Set last cleanup to now so maybe_cleanup skips
        buf._last_cleanup_ts = now
        buf.maybe_cleanup()
        # Should NOT have cleaned up (interval not passed)
        assert len(buf.get_events(1)) == 1

        # Set last cleanup to long ago
        buf._last_cleanup_ts = now - 700000
        buf.maybe_cleanup()
        # Should have cleaned up now
        assert len(buf.get_events(1)) == 0

    def test_get_latest_event(self):
        buf = EventRingBuffer()
        now = int(time.time() * 1000)

        buf.add(_make_event(timestamp=now - 1000))
        buf.add(_make_event(timestamp=now))

        latest = buf.get_latest_event(1)
        assert latest is not None
        assert latest.timestamp == now

    def test_get_latest_event_with_type(self):
        buf = EventRingBuffer()
        now = int(time.time() * 1000)

        buf.add(_make_event(event_type=EventType.PRICE_CHANGE, timestamp=now - 2000))
        buf.add(_make_event(event_type=EventType.TRADE, timestamp=now - 1000))
        buf.add(_make_event(event_type=EventType.PRICE_CHANGE, timestamp=now))

        latest_trade = buf.get_latest_event(1, event_type=EventType.TRADE)
        assert latest_trade is not None
        assert latest_trade.timestamp == now - 1000

    def test_get_latest_event_empty(self):
        buf = EventRingBuffer()
        assert buf.get_latest_event(999) is None

    def test_add_batch(self):
        buf = EventRingBuffer()
        events = [_make_event(market_id=i) for i in range(5)]
        buf.add_batch(events)

        assert buf.get_stats().total_events == 5
        assert buf.get_stats().total_markets == 5

    def test_get_market_ids(self):
        buf = EventRingBuffer()
        buf.add(_make_event(market_id=10))
        buf.add(_make_event(market_id=20))
        buf.add(_make_event(market_id=10))

        ids = buf.get_market_ids()
        assert set(ids) == {10, 20}

    def test_get_market_event_count(self):
        buf = EventRingBuffer()
        buf.add(_make_event(market_id=1))
        buf.add(_make_event(market_id=1))
        buf.add(_make_event(market_id=2))

        assert buf.get_market_event_count(1) == 2
        assert buf.get_market_event_count(2) == 1
        assert buf.get_market_event_count(999) == 0

    def test_stats(self):
        buf = EventRingBuffer()
        for i in range(3):
            buf.add(_make_event(market_id=i))

        stats = buf.get_stats()
        assert stats.total_events == 3
        assert stats.total_markets == 3
        assert stats.memory_estimate_mb >= 0  # 3 events is too small to register after rounding
        assert stats.events_added_total == 3
        assert stats.events_expired_total == 0

    def test_stats_memory_estimate(self):
        buf = EventRingBuffer()
        for i in range(1000):
            buf.add(_make_event(market_id=0, timestamp=int(time.time() * 1000) + i))

        stats = buf.get_stats()
        # 1000 events × 400 bytes ≈ 0.38 MB
        assert 0.3 < stats.memory_estimate_mb < 0.5

    def test_multiple_markets_isolated(self):
        buf = EventRingBuffer()
        buf.add(_make_event(market_id=1))
        buf.add(_make_event(market_id=1))
        buf.add(_make_event(market_id=2))

        assert len(buf.get_events(1)) == 2
        assert len(buf.get_events(2)) == 1

    def test_clear(self):
        buf = EventRingBuffer()
        buf.add(_make_event())
        buf.clear()
        assert buf.get_stats().total_events == 0
        assert buf.get_stats().total_markets == 0
        assert buf.get_stats().events_added_total == 0
