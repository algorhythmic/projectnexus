"""Tests for WindowComputer."""

import pytest

from nexus.core.types import (
    DiscoveredMarket,
    EventRecord,
    EventType,
    Platform,
)
from nexus.correlation.windows import WindowComputer


async def _setup_market(store, external_id: str = "WIN-TEST") -> int:
    """Insert a test market and return its id."""
    market = DiscoveredMarket(
        platform=Platform.KALSHI,
        external_id=external_id,
        title=f"Window Test {external_id}",
        yes_price=0.5,
    )
    await store.upsert_markets([market])
    stored = await store.get_market_by_external_id("kalshi", external_id)
    return stored.id


def _price_event(market_id: int, value: float, ts: int) -> EventRecord:
    return EventRecord(
        market_id=market_id,
        event_type=EventType.PRICE_CHANGE,
        new_value=value,
        timestamp=ts,
    )


def _trade_event(market_id: int, value: float, ts: int) -> EventRecord:
    return EventRecord(
        market_id=market_id,
        event_type=EventType.TRADE,
        new_value=value,
        timestamp=ts,
    )


def _volume_event(market_id: int, value: float, ts: int) -> EventRecord:
    return EventRecord(
        market_id=market_id,
        event_type=EventType.VOLUME_UPDATE,
        new_value=value,
        timestamp=ts,
    )


class TestWindowComputer:
    async def test_compute_window_with_price_events(self, tmp_store):
        """Price start/end/delta/change_pct computed from events."""
        mid = await _setup_market(tmp_store)
        now = 600_000  # 10 minutes in ms

        await tmp_store.insert_events([
            _price_event(mid, 0.50, 100_000),
            _price_event(mid, 0.55, 200_000),
            _price_event(mid, 0.60, 300_000),
        ])

        wc = WindowComputer(tmp_store)
        stats = await wc.compute_window(mid, 10, now)

        assert stats.price_start == 0.50
        assert stats.price_end == 0.60
        assert abs(stats.price_delta - 0.10) < 1e-9
        assert abs(stats.price_change_pct - 0.20) < 1e-9

    async def test_compute_window_empty(self, tmp_store):
        """Empty window returns zeroed stats."""
        mid = await _setup_market(tmp_store)
        wc = WindowComputer(tmp_store)
        stats = await wc.compute_window(mid, 5, 1000000)

        assert stats.price_start is None
        assert stats.price_end is None
        assert stats.volume_total == 0.0
        assert stats.trade_count == 0
        assert stats.event_count == 0

    async def test_compute_window_volume_aggregation(self, tmp_store):
        """Volume events are summed."""
        mid = await _setup_market(tmp_store)
        now = 600_000

        await tmp_store.insert_events([
            _volume_event(mid, 100.0, 100_000),
            _volume_event(mid, 200.0, 200_000),
            _volume_event(mid, 50.0, 300_000),
        ])

        wc = WindowComputer(tmp_store)
        stats = await wc.compute_window(mid, 10, now)

        assert stats.volume_total == 350.0

    async def test_compute_window_trade_count(self, tmp_store):
        """Trade events are counted."""
        mid = await _setup_market(tmp_store)
        now = 600_000

        await tmp_store.insert_events([
            _trade_event(mid, 1.0, 100_000),
            _trade_event(mid, 1.0, 200_000),
        ])

        wc = WindowComputer(tmp_store)
        stats = await wc.compute_window(mid, 10, now)

        assert stats.trade_count == 2

    async def test_trade_count_as_volume_proxy(self, tmp_store):
        """When no volume events, trade count is used as volume proxy."""
        mid = await _setup_market(tmp_store)
        now = 600_000

        await tmp_store.insert_events([
            _trade_event(mid, 1.0, 100_000),
            _trade_event(mid, 1.0, 200_000),
            _trade_event(mid, 1.0, 300_000),
        ])

        wc = WindowComputer(tmp_store)
        stats = await wc.compute_window(mid, 10, now)

        assert stats.volume_total == 3.0
        assert stats.trade_count == 3

    async def test_events_outside_window_excluded(self, tmp_store):
        """Events outside the time window are not included."""
        mid = await _setup_market(tmp_store)
        now = 600_000  # 10 min = 600_000ms, window_start = 300_000

        await tmp_store.insert_events([
            _price_event(mid, 0.50, 100_000),  # Outside window
            _price_event(mid, 0.70, 400_000),  # Inside window
        ])

        wc = WindowComputer(tmp_store)
        stats = await wc.compute_window(mid, 5, now)  # 5min window: 300k-600k

        assert stats.price_start == 0.70
        assert stats.price_end == 0.70
        assert stats.price_delta == 0.0

    async def test_compute_baseline_with_samples(self, tmp_store):
        """Baseline computes mean and stddev from sampled windows."""
        mid = await _setup_market(tmp_store)

        # Insert price events across multiple 5-min windows spanning 1 hour
        # Window 1: 0-300k ms -> 10% change
        await tmp_store.insert_events([
            _price_event(mid, 0.50, 10_000),
            _price_event(mid, 0.55, 200_000),
        ])
        # Window 2: 300k-600k ms -> 20% change
        await tmp_store.insert_events([
            _price_event(mid, 0.50, 310_000),
            _price_event(mid, 0.60, 500_000),
        ])

        wc = WindowComputer(tmp_store)
        baseline = await wc.compute_baseline(
            mid, "price_change_pct",
            lookback_hours=1, window_minutes=5, now_ms=3_600_000,
        )

        assert baseline.sample_count >= 2
        assert baseline.market_id == mid
        assert baseline.metric == "price_change_pct"

    async def test_compute_baseline_insufficient_data(self, tmp_store):
        """Baseline with no data returns zero mean/stddev."""
        mid = await _setup_market(tmp_store)

        wc = WindowComputer(tmp_store)
        baseline = await wc.compute_baseline(
            mid, "volume",
            lookback_hours=1, window_minutes=5, now_ms=3_600_000,
        )

        assert baseline.mean == 0.0
        assert baseline.stddev == 0.0
        assert baseline.sample_count == 0
