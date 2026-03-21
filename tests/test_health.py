"""Tests for the MarketHealthTracker (Feature A: Market Intelligence)."""

import json
import time

import pytest

from nexus.core.types import EventRecord, EventType
from nexus.intelligence.health import (
    MarketHealthTracker,
    MarketState,
    OrderbookSnapshot,
    TradeRecord,
    HealthComponents,
    TRADE_WINDOW_SECONDS,
    MAX_TRADES_PER_MIN,
    WHALE_THRESHOLD,
)


@pytest.fixture
def tracker():
    """Create a fresh MarketHealthTracker."""
    return MarketHealthTracker(max_markets=100)


def _make_trade_event(
    ticker: str,
    price: float = 0.50,
    count: float = 10.0,
    taker_side: str = "yes",
    timestamp_ms: int = 0,
) -> EventRecord:
    """Helper to create a TRADE event."""
    if timestamp_ms == 0:
        timestamp_ms = int(time.time() * 1000)
    return EventRecord(
        market_id=1,
        event_type=EventType.TRADE,
        new_value=price,
        metadata=json.dumps({
            "ticker": ticker,
            "count": str(count),
            "taker_side": taker_side,
            "side": taker_side,
        }),
        timestamp=timestamp_ms,
    )


def _make_price_event(
    ticker: str,
    price: float = 0.50,
    timestamp_ms: int = 0,
) -> EventRecord:
    """Helper to create a PRICE_CHANGE event."""
    if timestamp_ms == 0:
        timestamp_ms = int(time.time() * 1000)
    return EventRecord(
        market_id=1,
        event_type=EventType.PRICE_CHANGE,
        new_value=price,
        metadata=json.dumps({"ticker": ticker}),
        timestamp=timestamp_ms,
    )


class TestProcessEvent:
    """Test event processing and state accumulation."""

    def test_trade_event_creates_market_state(self, tracker):
        """Processing a trade event creates state for the market."""
        event = _make_trade_event("TEST-1")
        tracker.process_event(event)
        assert tracker.tracked_count == 1
        assert "TEST-1" in tracker._markets

    def test_trade_event_records_trade(self, tracker):
        """Trade event is added to the rolling trade window."""
        event = _make_trade_event("TEST-1", price=0.60, count=5.0)
        tracker.process_event(event)
        state = tracker._markets["TEST-1"]
        assert len(state.trades) == 1
        assert state.trades[0].price == 0.60
        assert state.trades[0].size == 5.0

    def test_trade_event_records_price(self, tracker):
        """Trade event also records a price point for momentum."""
        event = _make_trade_event("TEST-1", price=0.55)
        tracker.process_event(event)
        state = tracker._markets["TEST-1"]
        assert len(state.prices) == 1

    def test_price_event_records_price(self, tracker):
        """PRICE_CHANGE event records a price point."""
        event = _make_price_event("TEST-1", price=0.70)
        tracker.process_event(event)
        state = tracker._markets["TEST-1"]
        assert len(state.prices) == 1
        assert state.prices[0][1] == 0.70

    def test_multiple_trades_accumulate(self, tracker):
        """Multiple trades for the same market accumulate."""
        for i in range(10):
            tracker.process_event(_make_trade_event("TEST-1", price=0.50 + i * 0.01))
        state = tracker._markets["TEST-1"]
        assert len(state.trades) == 10
        assert len(state.prices) == 10

    def test_missing_metadata_skipped(self, tracker):
        """Events without metadata are silently skipped."""
        event = EventRecord(
            market_id=1,
            event_type=EventType.TRADE,
            new_value=0.5,
            metadata=None,
            timestamp=int(time.time() * 1000),
        )
        tracker.process_event(event)
        assert tracker.tracked_count == 0

    def test_missing_ticker_skipped(self, tracker):
        """Events with metadata but no ticker are skipped."""
        event = EventRecord(
            market_id=1,
            event_type=EventType.TRADE,
            new_value=0.5,
            metadata=json.dumps({"count": "10"}),
            timestamp=int(time.time() * 1000),
        )
        tracker.process_event(event)
        assert tracker.tracked_count == 0


class TestTradeVelocity:
    """Test trade velocity signal."""

    def test_no_trades_zero_velocity(self, tracker):
        """No trades → velocity 0.0."""
        components = tracker.compute_health("NONEXISTENT")
        assert components.trade_velocity == 0.0

    def test_moderate_trading(self, tracker):
        """Several trades in the window produce moderate velocity."""
        now_ms = int(time.time() * 1000)
        for i in range(30):
            tracker.process_event(_make_trade_event(
                "ACTIVE-1", price=0.50, timestamp_ms=now_ms - (i * 10000)
            ))
        components = tracker.compute_health("ACTIVE-1")
        assert 0.0 < components.trade_velocity < 1.0

    def test_high_trading_caps_at_one(self, tracker):
        """Very high trading rate caps velocity at 1.0."""
        now_ms = int(time.time() * 1000)
        # 200 trades in 15 minutes = 13.3/min > MAX_TRADES_PER_MIN
        for i in range(200):
            tracker.process_event(_make_trade_event(
                "HOT-1", price=0.50, timestamp_ms=now_ms - (i * 4500)
            ))
        components = tracker.compute_health("HOT-1")
        assert components.trade_velocity == 1.0


class TestOrderbookImbalance:
    """Test orderbook imbalance signal."""

    def test_no_orderbook_zero_imbalance(self, tracker):
        """No orderbook → imbalance 0.0."""
        tracker.process_event(_make_trade_event("NO-OB"))
        components = tracker.compute_health("NO-OB")
        assert components.orderbook_imbalance == 0.0
        assert components.has_orderbook is False

    def test_balanced_orderbook(self, tracker):
        """Equal bid/ask depth → imbalance 0.0."""
        tracker.process_event(_make_trade_event("BALANCED"))
        tracker.update_orderbook("BALANCED", OrderbookSnapshot(
            timestamp=time.time(),
            bid_depth=100.0,
            ask_depth=100.0,
            best_bid=0.49,
            best_ask=0.51,
            spread=0.02,
            levels=10,
        ))
        components = tracker.compute_health("BALANCED")
        assert components.orderbook_imbalance == 0.0
        assert components.has_orderbook is True

    def test_imbalanced_orderbook(self, tracker):
        """Heavy bid side → high imbalance."""
        tracker.process_event(_make_trade_event("IMBALANCED"))
        tracker.update_orderbook("IMBALANCED", OrderbookSnapshot(
            timestamp=time.time(),
            bid_depth=900.0,
            ask_depth=100.0,
            best_bid=0.49,
            best_ask=0.51,
            spread=0.02,
            levels=10,
        ))
        components = tracker.compute_health("IMBALANCED")
        assert components.orderbook_imbalance == 0.8  # |900-100|/(900+100)


class TestWhaleActivity:
    """Test whale activity signal."""

    def test_no_whales(self, tracker):
        """All small trades → whale activity 0.0."""
        now_ms = int(time.time() * 1000)
        for i in range(10):
            tracker.process_event(_make_trade_event(
                "RETAIL", price=0.50, count=5.0, timestamp_ms=now_ms - i * 1000
            ))
        components = tracker.compute_health("RETAIL")
        assert components.whale_activity == 0.0

    def test_whale_dominated(self, tracker):
        """Large trades dominate → whale activity near 1.0."""
        now_ms = int(time.time() * 1000)
        # One whale trade: $0.50 * 2000 = $1000 > $500 threshold
        tracker.process_event(_make_trade_event(
            "WHALE", price=0.50, count=2000.0, timestamp_ms=now_ms
        ))
        # One small trade: $0.50 * 5 = $2.50
        tracker.process_event(_make_trade_event(
            "WHALE", price=0.50, count=5.0, timestamp_ms=now_ms - 1000
        ))
        components = tracker.compute_health("WHALE")
        assert components.whale_activity > 0.9


class TestSpreadTightness:
    """Test spread tightness signal."""

    def test_no_orderbook_neutral(self, tracker):
        """No orderbook → default 0.5."""
        tracker.process_event(_make_trade_event("NO-SPREAD"))
        components = tracker.compute_health("NO-SPREAD")
        assert components.spread_tightness == 0.5

    def test_tight_spread(self, tracker):
        """Small spread → high tightness."""
        tracker.process_event(_make_trade_event("TIGHT"))
        tracker.update_orderbook("TIGHT", OrderbookSnapshot(
            timestamp=time.time(),
            bid_depth=100.0,
            ask_depth=100.0,
            best_bid=0.50,
            best_ask=0.51,
            spread=0.01,
            levels=10,
        ))
        components = tracker.compute_health("TIGHT")
        assert components.spread_tightness == 0.9  # 1 - 0.01/0.10

    def test_wide_spread(self, tracker):
        """Wide spread → low tightness."""
        tracker.process_event(_make_trade_event("WIDE"))
        tracker.update_orderbook("WIDE", OrderbookSnapshot(
            timestamp=time.time(),
            bid_depth=100.0,
            ask_depth=100.0,
            best_bid=0.40,
            best_ask=0.50,
            spread=0.10,
            levels=10,
        ))
        components = tracker.compute_health("WIDE")
        assert components.spread_tightness == 0.0


class TestMomentum:
    """Test momentum signal."""

    def test_no_prices_zero_momentum(self, tracker):
        """Less than 3 price points → momentum 0.0."""
        tracker.process_event(_make_price_event("FEW"))
        tracker.process_event(_make_price_event("FEW", 0.51))
        components = tracker.compute_health("FEW")
        assert components.momentum == 0.0

    def test_consistent_upward_momentum(self, tracker):
        """Consistently rising prices → high momentum."""
        now_ms = int(time.time() * 1000)
        for i in range(20):
            tracker.process_event(_make_price_event(
                "UP", price=0.40 + i * 0.01, timestamp_ms=now_ms - (20 - i) * 5000
            ))
        components = tracker.compute_health("UP")
        assert components.momentum > 0.5

    def test_oscillating_zero_momentum(self, tracker):
        """Alternating up/down → low momentum."""
        now_ms = int(time.time() * 1000)
        for i in range(20):
            price = 0.50 + (0.01 if i % 2 == 0 else -0.01)
            tracker.process_event(_make_price_event(
                "ZIGZAG", price=price, timestamp_ms=now_ms - (20 - i) * 5000
            ))
        components = tracker.compute_health("ZIGZAG")
        assert components.momentum < 0.3


class TestHealthScore:
    """Test the synthesized health score."""

    def test_empty_market_zero_score(self, tracker):
        """Market with no data → zero health score."""
        components = tracker.compute_health("EMPTY")
        assert components.health_score == 0.0

    def test_active_market_nonzero(self, tracker):
        """Market with trades and orderbook → positive health score."""
        now_ms = int(time.time() * 1000)
        for i in range(15):
            tracker.process_event(_make_trade_event(
                "ACTIVE", price=0.50 + i * 0.005, count=50.0,
                timestamp_ms=now_ms - i * 5000,
            ))
        tracker.update_orderbook("ACTIVE", OrderbookSnapshot(
            timestamp=time.time(),
            bid_depth=200.0,
            ask_depth=150.0,
            best_bid=0.57,
            best_ask=0.58,
            spread=0.01,
            levels=8,
        ))
        components = tracker.compute_health("ACTIVE")
        assert components.health_score > 0.0
        assert components.trade_count == 15
        assert components.has_orderbook is True

    def test_health_score_bounded(self, tracker):
        """Health score is always in [0, 1]."""
        now_ms = int(time.time() * 1000)
        for i in range(100):
            tracker.process_event(_make_trade_event(
                "EXTREME", price=0.90, count=5000.0,
                taker_side="yes", timestamp_ms=now_ms - i * 1000,
            ))
        tracker.update_orderbook("EXTREME", OrderbookSnapshot(
            timestamp=time.time(),
            bid_depth=10000.0,
            ask_depth=10.0,
            best_bid=0.90,
            best_ask=0.91,
            spread=0.01,
            levels=20,
        ))
        components = tracker.compute_health("EXTREME")
        assert 0.0 <= components.health_score <= 1.0


class TestGetHealthScores:
    """Test bulk score retrieval."""

    def test_returns_dict(self, tracker):
        """get_health_scores returns a dict of ticker→score."""
        now_ms = int(time.time() * 1000)
        for ticker in ["A", "B", "C"]:
            tracker.process_event(_make_trade_event(ticker, timestamp_ms=now_ms))
        scores = tracker.get_health_scores()
        assert isinstance(scores, dict)
        assert len(scores) == 3
        for score in scores.values():
            assert 0.0 <= score <= 1.0

    def test_excludes_inactive_markets(self, tracker):
        """Markets with no recent activity are excluded."""
        # Only price event, no trades → trade_count=0, no orderbook
        tracker.process_event(_make_price_event("QUIET"))
        scores = tracker.get_health_scores()
        assert "QUIET" not in scores


class TestOrderbookParsing:
    """Test parse_orderbook_response helper."""

    def test_parse_valid_orderbook(self):
        """Valid orderbook response is parsed correctly."""
        data = {
            "orderbook": {
                "yes": [[0.50, 100], [0.49, 200]],
                "no": [[0.50, 150], [0.51, 50]],
            }
        }
        ob = MarketHealthTracker.parse_orderbook_response(data)
        assert ob is not None
        assert ob.bid_depth == 300.0  # 100 + 200
        assert ob.ask_depth == 200.0  # 150 + 50
        assert ob.best_bid == 0.50
        assert ob.levels == 4

    def test_parse_empty_orderbook(self):
        """Empty orderbook returns None."""
        data = {"orderbook": {"yes": [], "no": []}}
        ob = MarketHealthTracker.parse_orderbook_response(data)
        assert ob is None

    def test_parse_missing_orderbook(self):
        """Missing orderbook key returns None."""
        data = {}
        ob = MarketHealthTracker.parse_orderbook_response(data)
        assert ob is None


class TestPruneStale:
    """Test memory cleanup."""

    def test_prune_removes_old_markets(self, tracker):
        """Markets with no recent activity are pruned."""
        # Create a market with old timestamps
        state = tracker._get_or_create("OLD")
        state.trades.append(TradeRecord(
            timestamp=time.time() - 7200,  # 2 hours ago
            price=0.50, size=10.0, taker_side="yes", dollar_value=5.0,
        ))
        state.prices.append((time.time() - 7200, 0.50))

        # Create a fresh market
        tracker.process_event(_make_trade_event("FRESH"))

        pruned = tracker.prune_stale(max_age_seconds=3600)
        assert pruned == 1
        assert "OLD" not in tracker._markets
        assert "FRESH" in tracker._markets

    def test_capacity_eviction(self, tracker):
        """Tracker evicts oldest markets at capacity."""
        small_tracker = MarketHealthTracker(max_markets=3)
        for ticker in ["A", "B", "C", "D"]:
            small_tracker.process_event(_make_trade_event(ticker))
        assert small_tracker.tracked_count <= 3
