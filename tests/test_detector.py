"""Tests for AnomalyDetector."""

import pytest

from nexus.core.types import (
    AnomalyType,
    DiscoveredMarket,
    EventRecord,
    EventType,
    Platform,
    WindowConfig,
)
from nexus.correlation.detector import AnomalyDetector
from nexus.correlation.windows import WindowComputer


async def _setup_market(store, external_id: str = "DET-TEST") -> int:
    market = DiscoveredMarket(
        platform=Platform.KALSHI,
        external_id=external_id,
        title=f"Detector Test {external_id}",
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


def _default_config(window_minutes: int = 5) -> WindowConfig:
    return WindowConfig(
        window_minutes=window_minutes,
        price_change_threshold=0.10,
        volume_spike_multiplier=3.0,
        zscore_threshold=2.5,
    )


class TestAnomalyDetector:
    async def test_price_threshold_triggers(self, tmp_store):
        """Large price change triggers an anomaly."""
        mid = await _setup_market(tmp_store)
        now = 600_000

        await tmp_store.insert_events([
            _price_event(mid, 0.50, 100_000),
            _price_event(mid, 0.70, 300_000),  # 40% increase
        ])

        wc = WindowComputer(tmp_store)
        detector = AnomalyDetector(tmp_store, wc, baseline_hours=1)
        anomalies = await detector.detect_market(mid, [_default_config(10)], now)

        assert len(anomalies) >= 1
        assert anomalies[0].anomaly_type == AnomalyType.SINGLE_MARKET
        assert anomalies[0].severity > 0

    async def test_price_below_threshold_no_anomaly(self, tmp_store):
        """Small price change does not trigger."""
        mid = await _setup_market(tmp_store)
        now = 600_000

        await tmp_store.insert_events([
            _price_event(mid, 0.50, 100_000),
            _price_event(mid, 0.52, 300_000),  # 4% increase, below 10%
        ])

        wc = WindowComputer(tmp_store)
        detector = AnomalyDetector(tmp_store, wc, baseline_hours=1)
        anomalies = await detector.detect_market(mid, [_default_config(10)], now)

        assert len(anomalies) == 0

    async def test_no_events_no_anomaly(self, tmp_store):
        """Empty market produces no anomalies."""
        mid = await _setup_market(tmp_store)

        wc = WindowComputer(tmp_store)
        detector = AnomalyDetector(tmp_store, wc, baseline_hours=1)
        anomalies = await detector.detect_market(mid, [_default_config()], 1000000)

        assert len(anomalies) == 0

    async def test_severity_scoring(self, tmp_store):
        """Severity scales with how much the threshold is exceeded."""
        mid = await _setup_market(tmp_store)
        now = 600_000

        # 100% price change — should produce high severity
        await tmp_store.insert_events([
            _price_event(mid, 0.30, 100_000),
            _price_event(mid, 0.60, 300_000),
        ])

        wc = WindowComputer(tmp_store)
        detector = AnomalyDetector(tmp_store, wc, baseline_hours=1)
        anomalies = await detector.detect_market(mid, [_default_config(10)], now)

        assert len(anomalies) >= 1
        assert anomalies[0].severity > 0.5

    async def test_detect_all_multiple_markets(self, tmp_store):
        """detect_all scans multiple markets."""
        mid1 = await _setup_market(tmp_store, "DET-1")
        mid2 = await _setup_market(tmp_store, "DET-2")
        now = 600_000

        # Spike on market 1 only
        await tmp_store.insert_events([
            _price_event(mid1, 0.50, 100_000),
            _price_event(mid1, 0.80, 300_000),  # 60% spike
            _price_event(mid2, 0.50, 100_000),
            _price_event(mid2, 0.51, 300_000),  # 2% — no anomaly
        ])

        wc = WindowComputer(tmp_store)
        detector = AnomalyDetector(tmp_store, wc, baseline_hours=1)
        anomalies = await detector.detect_all(
            [mid1, mid2], [_default_config(10)], now
        )

        # Only market 1 should trigger
        assert len(anomalies) >= 1
        assert all(a.anomaly_type == AnomalyType.SINGLE_MARKET for a in anomalies)

    async def test_summary_contains_info(self, tmp_store):
        """Anomaly summary includes useful context."""
        mid = await _setup_market(tmp_store)
        now = 600_000

        await tmp_store.insert_events([
            _price_event(mid, 0.50, 100_000),
            _price_event(mid, 0.75, 300_000),
        ])

        wc = WindowComputer(tmp_store)
        detector = AnomalyDetector(tmp_store, wc, baseline_hours=1)
        anomalies = await detector.detect_market(mid, [_default_config(10)], now)

        assert len(anomalies) >= 1
        assert "price" in anomalies[0].summary.lower()
        assert str(mid) in anomalies[0].summary

    async def test_detect_and_store(self, tmp_store):
        """detect_and_store persists anomalies to the database."""
        mid = await _setup_market(tmp_store)
        now = 600_000

        await tmp_store.insert_events([
            _price_event(mid, 0.50, 100_000),
            _price_event(mid, 0.80, 300_000),
        ])

        wc = WindowComputer(tmp_store)
        detector = AnomalyDetector(tmp_store, wc, baseline_hours=1)
        count = await detector.detect_and_store(
            [mid], [_default_config(10)], now
        )

        assert count >= 1
        stored = await tmp_store.get_anomalies()
        assert len(stored) >= 1

    async def test_multiple_window_configs(self, tmp_store):
        """Multiple window configs can each produce anomalies."""
        mid = await _setup_market(tmp_store)
        now = 600_000

        await tmp_store.insert_events([
            _price_event(mid, 0.50, 100_000),
            _price_event(mid, 0.80, 300_000),
        ])

        configs = [_default_config(5), _default_config(10)]

        wc = WindowComputer(tmp_store)
        detector = AnomalyDetector(tmp_store, wc, baseline_hours=1)
        anomalies = await detector.detect_market(mid, configs, now)

        # The 10-min window should see both events; 5-min may or may not
        assert len(anomalies) >= 1

    async def test_parse_window_minutes(self, tmp_store):
        """_parse_window_minutes extracts window size from summary."""
        assert AnomalyDetector._parse_window_minutes("market_id=42: +10% price in 60min window") == 60
        assert AnomalyDetector._parse_window_minutes("in 5min window") == 5
        assert AnomalyDetector._parse_window_minutes("no match") is None
        assert AnomalyDetector._parse_window_minutes("") is None
