"""Sliding window computation over the event store or ring buffer."""

import statistics
from typing import TYPE_CHECKING, List, Optional

from nexus.core.logging import LoggerMixin
from nexus.core.types import EventType, HistoricalBaseline, WindowStats
from nexus.store.base import BaseStore

if TYPE_CHECKING:
    from nexus.ingestion.ring_buffer import EventRingBuffer


class WindowComputer(LoggerMixin):
    """Computes windowed statistics for a market.

    Reads from an in-memory ring buffer when available (zero latency).
    Falls back to the PostgreSQL store when the buffer is empty
    (cold start, or events predate the buffer's max_age).
    """

    def __init__(
        self,
        store: BaseStore,
        ring_buffer: Optional["EventRingBuffer"] = None,
    ) -> None:
        self._store = store
        self._ring_buffer = ring_buffer

    async def compute_window(
        self, market_id: int, window_minutes: int, now_ms: int
    ) -> WindowStats:
        """Compute statistics for a single market in a time window."""
        window_start = now_ms - (window_minutes * 60 * 1000)
        window_end = now_ms

        # Try ring buffer first (zero-latency, in-memory)
        if self._ring_buffer is not None:
            price_events = self._ring_buffer.get_events(
                market_id, since_ts=window_start, event_type=EventType.PRICE_CHANGE
            )
            trade_events = self._ring_buffer.get_events(
                market_id, since_ts=window_start, event_type=EventType.TRADE
            )
            volume_events = self._ring_buffer.get_events(
                market_id, since_ts=window_start, event_type=EventType.VOLUME_UPDATE
            )

            # Use buffer data if we have any events at all
            if price_events or trade_events or volume_events:
                return self._build_stats(
                    market_id, window_minutes, window_start, window_end,
                    price_events, trade_events, volume_events,
                )

        # Fallback to PostgreSQL (cold start or buffer miss)
        price_events = await self._store.get_events_in_window(
            market_id, EventType.PRICE_CHANGE.value, window_start, window_end
        )
        trade_events = await self._store.get_events_in_window(
            market_id, EventType.TRADE.value, window_start, window_end
        )
        volume_events = await self._store.get_events_in_window(
            market_id, EventType.VOLUME_UPDATE.value, window_start, window_end
        )

        return self._build_stats(
            market_id, window_minutes, window_start, window_end,
            price_events, trade_events, volume_events,
        )

    @staticmethod
    def _build_stats(
        market_id: int,
        window_minutes: int,
        window_start: int,
        window_end: int,
        price_events: list,
        trade_events: list,
        volume_events: list,
    ) -> WindowStats:
        """Build WindowStats from event lists (works for both buffer and PG events)."""
        price_start: Optional[float] = None
        price_end: Optional[float] = None
        price_delta: Optional[float] = None
        price_change_pct: Optional[float] = None

        if price_events:
            price_start = price_events[0].new_value
            price_end = price_events[-1].new_value
            price_delta = price_end - price_start
            if price_start != 0:
                price_change_pct = price_delta / price_start

        trade_count = len(trade_events)

        volume_total = sum(e.new_value for e in volume_events)
        # If no volume events, use trade count as proxy
        if not volume_events and trade_count > 0:
            volume_total = float(trade_count)

        event_count = len(price_events) + len(trade_events) + len(volume_events)

        return WindowStats(
            market_id=market_id,
            window_minutes=window_minutes,
            window_start=window_start,
            window_end=window_end,
            price_start=price_start,
            price_end=price_end,
            price_delta=price_delta,
            price_change_pct=price_change_pct,
            volume_total=volume_total,
            trade_count=trade_count,
            event_count=event_count,
        )

    async def compute_baseline(
        self,
        market_id: int,
        metric: str,
        lookback_hours: int,
        window_minutes: int,
        now_ms: int,
    ) -> HistoricalBaseline:
        """Compute historical baseline by sampling non-overlapping windows.

        Args:
            market_id: Market to analyze.
            metric: "price_change_pct" or "volume".
            lookback_hours: How far back to sample.
            window_minutes: Size of each sample window.
            now_ms: Current timestamp in Unix ms.

        Returns:
            HistoricalBaseline with mean, stddev, and sample count.
        """
        lookback_ms = lookback_hours * 3600 * 1000
        window_ms = window_minutes * 60 * 1000
        start = now_ms - lookback_ms

        samples: List[float] = []
        cursor = start

        while cursor + window_ms <= now_ms:
            stats = await self.compute_window(market_id, window_minutes, cursor + window_ms)

            if stats.event_count == 0:
                cursor += window_ms
                continue

            value: Optional[float] = None
            if metric == "price_change_pct" and stats.price_change_pct is not None:
                value = stats.price_change_pct
            elif metric == "volume":
                value = stats.volume_total

            if value is not None:
                samples.append(value)

            cursor += window_ms

        if len(samples) >= 2:
            mean = statistics.mean(samples)
            stddev = statistics.stdev(samples)
        elif len(samples) == 1:
            mean = samples[0]
            stddev = 0.0
        else:
            mean = 0.0
            stddev = 0.0

        return HistoricalBaseline(
            market_id=market_id,
            metric=metric,
            mean=mean,
            stddev=stddev,
            sample_count=len(samples),
        )
