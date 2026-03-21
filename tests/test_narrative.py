"""Tests for the CatalystAnalyzer (Phase 5 prep)."""

import json
import time

import pytest

from nexus.core.types import EventRecord, EventType, MarketRecord, Platform
from nexus.intelligence.narrative import CatalystAnalyzer, CatalystAnalysis


@pytest.fixture
def analyzer():
    return CatalystAnalyzer()


def _make_price_event(price: float, ts_offset_ms: int = 0) -> EventRecord:
    now = int(time.time() * 1000)
    return EventRecord(
        market_id=1,
        event_type=EventType.PRICE_CHANGE,
        new_value=price,
        timestamp=now - ts_offset_ms,
    )


def _make_trade_event(
    price: float,
    count: float = 10.0,
    taker_side: str = "yes",
    ts_offset_ms: int = 0,
) -> EventRecord:
    now = int(time.time() * 1000)
    return EventRecord(
        market_id=1,
        event_type=EventType.TRADE,
        new_value=price,
        metadata=json.dumps({
            "ticker": "TEST-1",
            "count": str(count),
            "taker_side": taker_side,
        }),
        timestamp=now - ts_offset_ms,
    )


class TestPriceAnalysis:
    def test_upward_direction(self, analyzer):
        events = [
            _make_price_event(0.40, 10000),
            _make_price_event(0.50, 5000),
            _make_price_event(0.60, 0),
        ]
        result = analyzer.analyze_events(events)
        assert result.direction == "up"
        assert result.magnitude_pct == pytest.approx(0.5, abs=0.01)
        assert result.price_from == 0.40
        assert result.price_to == 0.60

    def test_downward_direction(self, analyzer):
        events = [
            _make_price_event(0.80, 10000),
            _make_price_event(0.60, 0),
        ]
        result = analyzer.analyze_events(events)
        assert result.direction == "down"
        assert result.magnitude_pct == pytest.approx(0.25, abs=0.01)

    def test_no_price_events(self, analyzer):
        result = analyzer.analyze_events([])
        assert result.direction == "unknown"
        assert result.magnitude_pct == 0.0


class TestTradeFlowAnalysis:
    def test_whale_detection(self, analyzer):
        events = [
            # One whale trade: 0.50 * 2000 = $1000 > $500
            _make_trade_event(0.50, count=2000.0, ts_offset_ms=5000),
            # Small trades
            _make_trade_event(0.50, count=5.0, ts_offset_ms=3000),
            _make_trade_event(0.50, count=5.0, ts_offset_ms=1000),
        ]
        result = analyzer.analyze_events(events)
        assert result.trade_count == 3
        assert result.whale_trade_pct > 0.9

    def test_taker_buy_pct(self, analyzer):
        events = [
            _make_trade_event(0.50, count=10.0, taker_side="yes", ts_offset_ms=3000),
            _make_trade_event(0.50, count=10.0, taker_side="yes", ts_offset_ms=2000),
            _make_trade_event(0.50, count=10.0, taker_side="no", ts_offset_ms=1000),
        ]
        result = analyzer.analyze_events(events)
        assert result.taker_buy_pct == pytest.approx(2 / 3, abs=0.01)

    def test_no_trades(self, analyzer):
        events = [_make_price_event(0.50)]
        result = analyzer.analyze_events(events)
        assert result.trade_count == 0
        assert result.trades_per_minute == 0.0


class TestBurstDetection:
    def test_detects_burst(self, analyzer):
        now = int(time.time() * 1000)
        # 8 trades in first 2 minutes, 2 trades spread over remaining 13 minutes
        events = [
            _make_trade_event(0.50, ts_offset_ms=14 * 60000),
            _make_trade_event(0.50, ts_offset_ms=10 * 60000),
        ]
        # Burst: 8 trades in 2 minutes (concentrated)
        for i in range(8):
            events.append(_make_trade_event(0.50, ts_offset_ms=i * 10000))

        result = analyzer.analyze_events(events, window_minutes=15)
        assert result.burst_detected is True
        assert result.burst_trade_pct >= 0.6

    def test_no_burst_evenly_spread(self, analyzer):
        # 10 trades evenly spread over 15 minutes
        events = [
            _make_trade_event(0.50, ts_offset_ms=i * 90000)
            for i in range(10)
        ]
        result = analyzer.analyze_events(events, window_minutes=15)
        assert result.burst_detected is False


class TestCatalystInference:
    def test_whale_catalyst(self, analyzer):
        events = [
            _make_price_event(0.40, 10000),
            _make_trade_event(0.50, count=2000.0, taker_side="yes", ts_offset_ms=5000),
            _make_trade_event(0.55, count=1500.0, taker_side="yes", ts_offset_ms=3000),
            _make_trade_event(0.60, count=5.0, taker_side="no", ts_offset_ms=0),
            _make_price_event(0.60, 0),
        ]
        result = analyzer.analyze_events(events)
        assert result.catalyst_type == "whale"
        assert result.confidence > 0.3

    def test_serialization(self, analyzer):
        events = [_make_price_event(0.50)]
        result = analyzer.analyze_events(events)
        d = result.to_dict()
        assert "direction" in d
        assert "catalyst_type" in d
        j = result.to_json()
        parsed = json.loads(j)
        assert parsed["direction"] == result.direction


class TestMarketContext:
    def test_adds_category(self, analyzer):
        market = MarketRecord(
            platform=Platform.KALSHI,
            external_id="BTC-50K-YES",
            title="BTC Above 50K",
            category="Cryptocurrency",
            first_seen_at=0,
            last_updated_at=0,
        )
        events = [_make_price_event(0.50)]
        result = analyzer.analyze_events(events, market=market)
        assert result.category == "Cryptocurrency"
        assert result.series_prefix == "BTC"
