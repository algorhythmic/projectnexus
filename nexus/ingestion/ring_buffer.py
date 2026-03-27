"""In-memory per-market event ring buffer.

Holds recent events in bounded deques for real-time windowed analysis.
Events are never persisted from here — they're consumed by WindowComputer
and CandleAggregator, then discarded when they age out of the deque.

Memory budget: ~400 bytes/event × 2000 events/market × 5,000 markets
             = ~200 MB for worst case. Typical usage much lower since
             most markets receive <100 events/day.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

from nexus.core.logging import LoggerMixin
from nexus.core.types import EventRecord, EventType


@dataclass
class BufferStats:
    """Snapshot of ring buffer state for monitoring."""

    total_events: int = 0
    total_markets: int = 0
    oldest_event_age_seconds: float = 0.0
    newest_event_age_seconds: float = 0.0
    memory_estimate_mb: float = 0.0
    events_added_total: int = 0
    events_expired_total: int = 0


class EventRingBuffer(LoggerMixin):
    """Per-market bounded event buffer with time-based expiry.

    Thread-safety: designed for single-threaded asyncio use within the
    ingestion TaskGroup. No locks needed — all access is from the same
    event loop.

    Usage::

        buffer = EventRingBuffer(max_age_seconds=86400, max_events_per_market=2000)
        buffer.add(event)
        events = buffer.get_events(market_id, since_ts=now - 3600000)
        stats = buffer.get_stats()
    """

    def __init__(
        self,
        max_age_seconds: int = 86400,  # 24 hours
        max_events_per_market: int = 2000,
        cleanup_interval_seconds: int = 300,  # Purge expired events every 5 min
    ):
        self._max_age_ms = max_age_seconds * 1000
        self._max_events = max_events_per_market
        self._cleanup_interval_ms = cleanup_interval_seconds * 1000

        # market_id -> deque of EventRecord, sorted by timestamp (oldest first)
        self._buffers: dict[int, deque[EventRecord]] = {}

        # Counters for monitoring
        self._events_added: int = 0
        self._events_expired: int = 0
        self._last_cleanup_ts: int = 0

    def add(self, event: EventRecord) -> None:
        """Add an event to the appropriate market buffer.

        If the deque exceeds max_events_per_market, the oldest event is
        silently dropped (deque handles this via maxlen).
        """
        market_id = event.market_id
        if market_id not in self._buffers:
            self._buffers[market_id] = deque(maxlen=self._max_events)

        self._buffers[market_id].append(event)
        self._events_added += 1

    def add_batch(self, events: list[EventRecord]) -> None:
        """Add multiple events. Used by the batch drain worker."""
        for event in events:
            self.add(event)

    def get_events(
        self,
        market_id: int,
        since_ts: Optional[int] = None,
        event_type: Optional[EventType] = None,
    ) -> list[EventRecord]:
        """Retrieve events for a market, optionally filtered by time and type.

        Returns list of EventRecord, oldest first.
        """
        buf = self._buffers.get(market_id)
        if not buf:
            return []

        results = []
        for event in buf:
            if since_ts is not None and event.timestamp < since_ts:
                continue
            if event_type is not None and event.event_type != event_type:
                continue
            results.append(event)

        return results

    def get_latest_event(
        self, market_id: int, event_type: Optional[EventType] = None
    ) -> Optional[EventRecord]:
        """Get the most recent event for a market."""
        buf = self._buffers.get(market_id)
        if not buf:
            return None

        if event_type is None:
            return buf[-1]

        # Walk backwards to find latest of this type
        for event in reversed(buf):
            if event.event_type == event_type:
                return event
        return None

    def get_market_ids(self) -> list[int]:
        """Return all market IDs that have buffered events."""
        return list(self._buffers.keys())

    def get_market_event_count(self, market_id: int) -> int:
        """Return number of buffered events for a market."""
        buf = self._buffers.get(market_id)
        return len(buf) if buf else 0

    def cleanup_expired(self) -> int:
        """Remove events older than max_age from all buffers.

        Called periodically by the ingestion manager, not on every add()
        (to avoid O(n) scans on the hot path).

        Returns number of events removed.
        """
        now_ms = int(time.time() * 1000)
        cutoff = now_ms - self._max_age_ms
        removed = 0

        empty_markets = []
        for market_id, buf in self._buffers.items():
            while buf and buf[0].timestamp < cutoff:
                buf.popleft()
                removed += 1

            if not buf:
                empty_markets.append(market_id)

        # Remove empty buffers to prevent unbounded dict growth
        for market_id in empty_markets:
            del self._buffers[market_id]

        self._events_expired += removed
        self._last_cleanup_ts = now_ms

        if removed > 0:
            self.logger.info(
                "ring_buffer_cleanup",
                removed=removed,
                empty_markets_removed=len(empty_markets),
                active_markets=len(self._buffers),
            )

        return removed

    def maybe_cleanup(self) -> None:
        """Run cleanup if enough time has passed since the last run."""
        now_ms = int(time.time() * 1000)
        if now_ms - self._last_cleanup_ts >= self._cleanup_interval_ms:
            self.cleanup_expired()

    def get_stats(self) -> BufferStats:
        """Snapshot of buffer state for health reporting."""
        now_ms = int(time.time() * 1000)
        total_events = sum(len(buf) for buf in self._buffers.values())

        oldest_age = 0.0
        newest_age = 0.0
        if self._buffers:
            all_oldest = [buf[0].timestamp for buf in self._buffers.values() if buf]
            all_newest = [buf[-1].timestamp for buf in self._buffers.values() if buf]
            if all_oldest:
                oldest_age = (now_ms - min(all_oldest)) / 1000.0
            if all_newest:
                newest_age = (now_ms - max(all_newest)) / 1000.0

        # Rough memory estimate: ~400 bytes per EventRecord in a deque
        # (Pydantic model + deque node overhead)
        memory_mb = (total_events * 400) / (1024 * 1024)

        return BufferStats(
            total_events=total_events,
            total_markets=len(self._buffers),
            oldest_event_age_seconds=oldest_age,
            newest_event_age_seconds=newest_age,
            memory_estimate_mb=round(memory_mb, 1),
            events_added_total=self._events_added,
            events_expired_total=self._events_expired,
        )

    def clear(self) -> None:
        """Clear all buffers. Used in testing."""
        self._buffers.clear()
        self._events_added = 0
        self._events_expired = 0
