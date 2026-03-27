"""In-memory OHLCV candle aggregation from the EventRingBuffer.

Reads price_change and trade events from the ring buffer, computes
1-minute candles per market, and periodically flushes completed candles
to the PostgreSQL ``candles`` table.

This replaces the ``compute_candlesticks()`` SQL function for new data.
Historical candles from before this migration remain queryable.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nexus.core.logging import LoggerMixin
from nexus.core.types import EventRecord, EventType

if TYPE_CHECKING:
    from nexus.ingestion.ring_buffer import EventRingBuffer
    from nexus.store.base import BaseStore


@dataclass
class CandleWindow:
    """An in-progress 1-minute candle for a single market."""

    market_id: int
    open_ts: int       # Window start (floored to minute boundary), Unix ms
    close_ts: int      # Window end (open_ts + 60000)
    open: float = 0.0
    high: float = 0.0
    low: float = float("inf")
    close: float = 0.0
    volume: int = 0
    trade_count: int = 0
    event_count: int = 0

    def update_price(self, price: float) -> None:
        """Update OHLC from a price_change event."""
        if self.event_count == 0:
            self.open = price
            self.high = price
            self.low = price
        else:
            self.high = max(self.high, price)
            self.low = min(self.low, price)
        self.close = price
        self.event_count += 1

    def update_trade(self, volume: int) -> None:
        """Update volume and trade count from a trade event."""
        self.volume += volume
        self.trade_count += 1

    def is_complete(self, now_ms: int) -> bool:
        """A candle is complete when current time exceeds its close_ts."""
        return now_ms >= self.close_ts

    def to_dict(self) -> dict:
        return {
            "market_id": self.market_id,
            "interval": "1m",
            "open_ts": self.open_ts,
            "close_ts": self.close_ts,
            "open": self.open,
            "high": self.high,
            "low": self.low if self.low != float("inf") else self.open,
            "close": self.close,
            "volume": self.volume,
            "trade_count": self.trade_count,
        }


class CandleAggregator(LoggerMixin):
    """Aggregates events from the ring buffer into 1-minute OHLCV candles.

    Runs as an asyncio task within the pipeline's TaskGroup.
    Flush interval is configurable (default: 30 seconds).
    """

    def __init__(
        self,
        ring_buffer: "EventRingBuffer",
        store: "BaseStore",
        flush_interval_seconds: int = 30,
    ):
        self._ring_buffer = ring_buffer
        self._store = store
        self._flush_interval = flush_interval_seconds

        # market_id -> current (incomplete) CandleWindow
        self._active_candles: dict[int, CandleWindow] = {}

        # Completed candles waiting to be flushed to PG
        self._pending_flush: list[dict] = []

        # Track which events we've already processed per market
        self._last_processed_ts: dict[int, int] = {}

        # Stats
        self._candles_flushed_total: int = 0
        self._running = False

    @staticmethod
    def _floor_to_minute(ts_ms: int) -> int:
        """Floor a Unix ms timestamp to the start of its minute."""
        return (ts_ms // 60000) * 60000

    def aggregate(self) -> None:
        """Scan the ring buffer for new events and update candle windows.

        Called periodically by the run loop. Processes only events newer
        than the last processed timestamp per market.
        """
        now_ms = int(time.time() * 1000)

        for market_id in self._ring_buffer.get_market_ids():
            since_ts = self._last_processed_ts.get(market_id, 0)
            events = self._ring_buffer.get_events(market_id, since_ts=since_ts)

            if not events:
                continue

            for event in events:
                minute_ts = self._floor_to_minute(event.timestamp)

                # Get or create candle window for this minute
                candle = self._active_candles.get(market_id)

                if candle is None or candle.open_ts != minute_ts:
                    # New minute boundary — finalize previous candle if it exists
                    if candle is not None and candle.event_count > 0:
                        self._pending_flush.append(candle.to_dict())

                    candle = CandleWindow(
                        market_id=market_id,
                        open_ts=minute_ts,
                        close_ts=minute_ts + 60000,
                    )
                    self._active_candles[market_id] = candle

                # Update candle from event
                if event.event_type == EventType.PRICE_CHANGE:
                    price = event.new_value
                    if price is not None and price > 0:
                        candle.update_price(price)
                elif event.event_type == EventType.TRADE:
                    volume = int(event.new_value) if event.new_value else 0
                    candle.update_trade(volume)

            # Update watermark
            self._last_processed_ts[market_id] = events[-1].timestamp + 1

        # Finalize any candles whose minute has passed
        for market_id, candle in list(self._active_candles.items()):
            if candle.is_complete(now_ms) and candle.event_count > 0:
                self._pending_flush.append(candle.to_dict())
                del self._active_candles[market_id]

    async def flush(self) -> int:
        """Flush completed candles to PostgreSQL. Returns count flushed."""
        if not self._pending_flush:
            return 0

        batch = self._pending_flush[:]
        self._pending_flush.clear()

        try:
            count = await self._store.insert_candles(batch)
            self._candles_flushed_total += count
            self.logger.info(
                "candles_flushed",
                count=count,
                total=self._candles_flushed_total,
            )
            return count
        except Exception as e:
            # Put them back for retry on next flush
            self._pending_flush.extend(batch)
            self.logger.error("candle_flush_failed", error=str(e))
            return 0

    async def run(self) -> None:
        """Main loop: aggregate events, flush completed candles."""
        self._running = True
        self.logger.info("candle_aggregator_started")
        while self._running:
            try:
                self.aggregate()
                await self.flush()
            except Exception as e:
                self.logger.error("candle_aggregator_error", error=str(e))

            await asyncio.sleep(self._flush_interval)

    async def stop(self) -> None:
        """Stop the aggregator loop."""
        self._running = False

    def get_stats(self) -> dict:
        return {
            "active_candles": len(self._active_candles),
            "pending_flush": len(self._pending_flush),
            "candles_flushed_total": self._candles_flushed_total,
            "markets_tracked": len(self._last_processed_ts),
        }
