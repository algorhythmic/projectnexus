"""Tests for the SeriesPatternDetector."""

import json
import time

import pytest

from nexus.core.types import (
    AnomalyRecord,
    AnomalyStatus,
    AnomalyType,
    DiscoveredMarket,
    EventRecord,
    EventType,
    Platform,
)
from nexus.correlation.series_detector import SeriesPatternDetector


class TestExtractSeriesPrefix:
    def test_standard_ticker(self):
        assert SeriesPatternDetector._extract_series_prefix("INXD-26MAR-B5825") == "INXD"

    def test_two_segment(self):
        assert SeriesPatternDetector._extract_series_prefix("BTC-50K") == "BTC"

    def test_single_segment(self):
        assert SeriesPatternDetector._extract_series_prefix("STANDALONE") is None


class TestSeriesDetection:
    """Integration tests using the tmp_store fixture."""

    async def _setup_series(self, store, prefix: str, count: int, price_base: float = 0.50):
        """Create a series of markets with price events showing movement."""
        now_ms = int(time.time() * 1000)
        markets = []
        for i in range(count):
            ticker = f"{prefix}-OUTCOME-{i}"
            market = DiscoveredMarket(
                platform=Platform.KALSHI,
                external_id=ticker,
                title=f"{prefix} Outcome {i}",
                yes_price=price_base,
            )
            markets.append(market)

        await store.upsert_markets(markets)

        # Insert price events showing movement
        market_ids = []
        for m in markets:
            stored = await store.get_market_by_external_id("kalshi", m.external_id)
            if stored and stored.id:
                market_ids.append(stored.id)

                # Two price events: showing upward movement
                events = [
                    EventRecord(
                        market_id=stored.id,
                        event_type=EventType.PRICE_CHANGE,
                        old_value=price_base,
                        new_value=price_base,
                        timestamp=now_ms - 600_000,  # 10 min ago
                    ),
                    EventRecord(
                        market_id=stored.id,
                        event_type=EventType.PRICE_CHANGE,
                        old_value=price_base,
                        new_value=price_base + 0.05,  # 5% move (>3% threshold)
                        timestamp=now_ms - 60_000,  # 1 min ago
                    ),
                ]
                await store.insert_events(events)

        return market_ids, now_ms

    async def test_detects_series_pattern(self, tmp_store):
        """Detects when 3+ markets in a series move together."""
        market_ids, now_ms = await self._setup_series(tmp_store, "BTC", 5)

        detector = SeriesPatternDetector(
            tmp_store, min_movers=3, window_minutes=30, price_threshold=0.03
        )
        count = await detector.detect_and_store(market_ids, now_ms)

        assert count == 1

        # Verify the anomaly was stored
        anomalies = await tmp_store.get_anomalies(since=now_ms - 1_800_000, limit=10)
        series_anomalies = [
            a for a in anomalies
            if a.metadata and "series_pattern" in a.metadata
        ]
        assert len(series_anomalies) == 1
        meta = json.loads(series_anomalies[0].metadata)
        assert meta["series_prefix"] == "BTC"
        assert meta["direction"] == "up"
        assert meta["movers"] >= 3

    async def test_skips_small_series(self, tmp_store):
        """Series with fewer than min_movers markets is skipped."""
        market_ids, now_ms = await self._setup_series(tmp_store, "TINY", 2)

        detector = SeriesPatternDetector(
            tmp_store, min_movers=3, window_minutes=30
        )
        count = await detector.detect_and_store(market_ids, now_ms)

        assert count == 0

    async def test_skips_no_movement(self, tmp_store):
        """Markets with prices that didn't change are not flagged."""
        now_ms = int(time.time() * 1000)
        markets = []
        for i in range(5):
            ticker = f"FLAT-OUTCOME-{i}"
            markets.append(DiscoveredMarket(
                platform=Platform.KALSHI,
                external_id=ticker,
                title=f"Flat {i}",
                yes_price=0.50,
            ))
        await tmp_store.upsert_markets(markets)

        market_ids = []
        for m in markets:
            stored = await tmp_store.get_market_by_external_id("kalshi", m.external_id)
            if stored and stored.id:
                market_ids.append(stored.id)
                # Two events at the SAME price — no movement
                events = [
                    EventRecord(
                        market_id=stored.id,
                        event_type=EventType.PRICE_CHANGE,
                        new_value=0.50,
                        timestamp=now_ms - 600_000,
                    ),
                    EventRecord(
                        market_id=stored.id,
                        event_type=EventType.PRICE_CHANGE,
                        new_value=0.50,
                        timestamp=now_ms - 60_000,
                    ),
                ]
                await tmp_store.insert_events(events)

        detector = SeriesPatternDetector(tmp_store, min_movers=3)
        count = await detector.detect_and_store(market_ids, now_ms)
        assert count == 0

    async def test_deduplicates(self, tmp_store):
        """Doesn't create duplicate anomalies for the same series/window."""
        market_ids, now_ms = await self._setup_series(tmp_store, "DUP", 5)

        detector = SeriesPatternDetector(tmp_store, min_movers=3, window_minutes=30)

        count1 = await detector.detect_and_store(market_ids, now_ms)
        count2 = await detector.detect_and_store(market_ids, now_ms)

        assert count1 == 1
        assert count2 == 0  # Deduplicated
