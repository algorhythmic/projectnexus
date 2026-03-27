"""Tests for CandleAggregator."""

import time
from unittest.mock import AsyncMock

import pytest

from nexus.core.types import EventRecord, EventType
from nexus.ingestion.candle_aggregator import CandleAggregator, CandleWindow
from nexus.ingestion.ring_buffer import EventRingBuffer


def _make_price_event(market_id: int, price: float, ts: int) -> EventRecord:
    return EventRecord(
        market_id=market_id,
        event_type=EventType.PRICE_CHANGE,
        timestamp=ts,
        new_value=price,
    )


def _make_trade_event(market_id: int, volume: int, ts: int) -> EventRecord:
    return EventRecord(
        market_id=market_id,
        event_type=EventType.TRADE,
        timestamp=ts,
        new_value=float(volume),
    )


class TestCandleWindow:
    def test_single_price_update(self):
        cw = CandleWindow(market_id=1, open_ts=0, close_ts=60000)
        cw.update_price(0.65)

        assert cw.open == 0.65
        assert cw.high == 0.65
        assert cw.low == 0.65
        assert cw.close == 0.65
        assert cw.event_count == 1

    def test_multiple_price_updates(self):
        cw = CandleWindow(market_id=1, open_ts=0, close_ts=60000)
        cw.update_price(0.50)
        cw.update_price(0.70)
        cw.update_price(0.55)

        assert cw.open == 0.50
        assert cw.high == 0.70
        assert cw.low == 0.50
        assert cw.close == 0.55
        assert cw.event_count == 3

    def test_trade_accumulation(self):
        cw = CandleWindow(market_id=1, open_ts=0, close_ts=60000)
        cw.update_trade(10)
        cw.update_trade(25)

        assert cw.volume == 35
        assert cw.trade_count == 2

    def test_is_complete(self):
        cw = CandleWindow(market_id=1, open_ts=0, close_ts=60000)
        assert not cw.is_complete(30000)
        assert cw.is_complete(60000)
        assert cw.is_complete(90000)

    def test_to_dict(self):
        cw = CandleWindow(market_id=1, open_ts=0, close_ts=60000)
        cw.update_price(0.50)
        cw.update_price(0.60)
        cw.update_trade(10)

        d = cw.to_dict()
        assert d["market_id"] == 1
        assert d["interval"] == "1m"
        assert d["open"] == 0.50
        assert d["close"] == 0.60
        assert d["high"] == 0.60
        assert d["low"] == 0.50
        assert d["volume"] == 10

    def test_to_dict_handles_inf_low(self):
        cw = CandleWindow(market_id=1, open_ts=0, close_ts=60000)
        # No events: low is still inf
        d = cw.to_dict()
        assert d["low"] == 0.0  # Falls back to open (which is 0.0)


class TestCandleAggregator:
    def _make_aggregator(self):
        buf = EventRingBuffer(max_age_seconds=3600)
        store = AsyncMock()
        store.insert_candles = AsyncMock(return_value=0)
        agg = CandleAggregator(buf, store, flush_interval_seconds=1)
        return agg, buf, store

    def test_aggregate_creates_active_candle(self):
        agg, buf, _ = self._make_aggregator()
        now = int(time.time() * 1000)
        minute_start = (now // 60000) * 60000

        buf.add(_make_price_event(1, 0.50, minute_start + 1000))
        buf.add(_make_price_event(1, 0.60, minute_start + 30000))
        buf.add(_make_trade_event(1, 10, minute_start + 15000))

        agg.aggregate()

        stats = agg.get_stats()
        assert stats["markets_tracked"] == 1

    def test_completed_candle_moves_to_pending(self):
        agg, buf, _ = self._make_aggregator()
        now = int(time.time() * 1000)

        # Events from 2 minutes ago (definitely completed)
        old_minute = ((now - 120000) // 60000) * 60000
        buf.add(_make_price_event(1, 0.50, old_minute + 1000))
        buf.add(_make_price_event(1, 0.60, old_minute + 30000))

        agg.aggregate()

        assert agg.get_stats()["pending_flush"] >= 1

    def test_candle_ohlcv_correctness(self):
        agg, buf, _ = self._make_aggregator()
        now = int(time.time() * 1000)

        # Use a completed minute (2 minutes ago)
        minute_start = ((now - 120000) // 60000) * 60000
        buf.add(_make_price_event(1, 0.50, minute_start + 1000))
        buf.add(_make_price_event(1, 0.70, minute_start + 10000))
        buf.add(_make_price_event(1, 0.45, minute_start + 20000))
        buf.add(_make_price_event(1, 0.60, minute_start + 30000))
        buf.add(_make_trade_event(1, 15, minute_start + 5000))
        buf.add(_make_trade_event(1, 25, minute_start + 25000))

        agg.aggregate()

        assert len(agg._pending_flush) >= 1
        candle = agg._pending_flush[0]
        assert candle["open"] == 0.50
        assert candle["high"] == 0.70
        assert candle["low"] == 0.45
        assert candle["close"] == 0.60
        assert candle["volume"] == 40
        assert candle["trade_count"] == 2

    async def test_flush_calls_store(self):
        agg, buf, store = self._make_aggregator()
        store.insert_candles.return_value = 1

        now = int(time.time() * 1000)
        old_minute = ((now - 120000) // 60000) * 60000
        buf.add(_make_price_event(1, 0.50, old_minute + 1000))

        agg.aggregate()
        count = await agg.flush()

        assert store.insert_candles.called
        assert count >= 0

    async def test_flush_retries_on_failure(self):
        agg, buf, store = self._make_aggregator()
        store.insert_candles.side_effect = Exception("DB error")

        agg._pending_flush = [{"market_id": 1, "interval": "1m", "open_ts": 0}]
        await agg.flush()

        # Failed items should be put back for retry
        assert len(agg._pending_flush) == 1

    async def test_flush_empty_is_noop(self):
        agg, _, store = self._make_aggregator()
        count = await agg.flush()
        assert count == 0
        store.insert_candles.assert_not_called()

    def test_multiple_markets(self):
        agg, buf, _ = self._make_aggregator()
        now = int(time.time() * 1000)
        old_minute = ((now - 120000) // 60000) * 60000

        buf.add(_make_price_event(1, 0.50, old_minute + 1000))
        buf.add(_make_price_event(2, 0.30, old_minute + 2000))
        buf.add(_make_price_event(3, 0.90, old_minute + 3000))

        agg.aggregate()

        assert agg.get_stats()["markets_tracked"] == 3

    def test_floor_to_minute(self):
        assert CandleAggregator._floor_to_minute(1710900030000) == 1710900000000
        assert CandleAggregator._floor_to_minute(1710900000000) == 1710900000000
        assert CandleAggregator._floor_to_minute(1710900059999) == 1710900000000

    def test_get_stats(self):
        agg, _, _ = self._make_aggregator()
        stats = agg.get_stats()
        assert stats["active_candles"] == 0
        assert stats["pending_flush"] == 0
        assert stats["candles_flushed_total"] == 0
        assert stats["markets_tracked"] == 0
