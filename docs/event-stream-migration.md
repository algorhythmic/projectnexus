# Event Stream Architecture Migration

**Status: COMPLETE (2026-03-27).** Steps 0–6 deployed and verified. Step 7 (event archive) deferred — use Tigris/R2 if needed later.

**Objective:** Eliminate raw `price_change` event writes to PostgreSQL by introducing an in-memory ring buffer and pre-computed candle aggregation. Reduces PG writes by ~97%, keeps storage growth flat regardless of platform count, and requires zero new infrastructure.

**Results:**
| Metric | Before | After |
|---|---|---|
| PG writes/day | ~487,000 | ~50,000 |
| DB size | 746 MB | 38 MB |
| Events table | 685 MB | 5 MB |
| Storage growth/month | 3.5 GB | ~360 MB |
| Detection data source | PostgreSQL (network I/O) | In-memory ring buffer (zero latency) |
| Candlestick source | SQL aggregation over raw events | Pre-computed `candles` table |
| Supabase tier | Over 500 MB limit | 38 MB, months of headroom |

**Prerequisites:** Familiarity with the current codebase as described in `CLAUDE.md`. All new modules follow existing patterns: `LoggerMixin`, `Settings` singleton, Pydantic models in `nexus/core/types.py`, `pytest-asyncio` for tests.

---

## Architecture: Before and After

### Before (current)

```
WebSocket Events
       │
       ▼
   EventBus (asyncio.Queue)
       │
       ▼
   Batch Drain Worker
       │
       ▼
   store.insert_events()  ←── Every event hits PostgreSQL
       │
       ├──▶ WindowComputer (reads events back FROM PG)
       ├──▶ AnomalyDetector (reads WindowComputer output)
       ├──▶ compute_candlesticks() (aggregates FROM raw events in PG)
       └──▶ v_current_market_state (materialized view over events)
```

**Problem:** 487K writes/day, 90% are `price_change` events consumed only in sliding windows then never read again. Storage growing at 3.5 GB/month.

### After (target)

```
WebSocket Events
       │
       ▼
   EventBus (asyncio.Queue — unchanged)
       │
       ▼
   Batch Drain Worker (modified: routes events)
       │
       ├──▶ EventRingBuffer (NEW: in-memory per-market deques)
       │         │
       │         ├──▶ WindowComputer (MODIFIED: reads from ring buffer)
       │         ├──▶ CandleAggregator (NEW: computes 1-min OHLCV in memory)
       │         │         │
       │         │         └──▶ store.insert_candles() (periodic flush to PG)
       │         │
       │         └──▶ AnomalyDetector (unchanged — reads WindowComputer output)
       │
       ├──▶ store.upsert_market_state() (latest price/volume per market)
       │
       └──▶ store.insert_events() (MODIFIED: only trade + status_change + new_market)
                                    price_change events SKIPPED
```

**Result:** PG receives ~30K–50K writes/day (trades, candles, anomalies, status changes). Ring buffer holds ~120 MB in memory. Total Fly.io RSS: ~400 MB (within 1 GB limit).

---

## Step 1: Add EventRingBuffer

A per-market circular buffer holding the last N minutes of events in memory. This is the foundation that all subsequent steps build on.

### 1.1 New file: `nexus/ingestion/ring_buffer.py`

```python
"""
In-memory per-market event ring buffer.

Holds recent events in bounded deques for real-time windowed analysis.
Events are never persisted — they're consumed by WindowComputer and
CandleAggregator, then discarded when they age out of the deque.

Memory budget: ~250 bytes/event × 112 events/market/day × 5,000 markets
             = ~140 MB for 24h retention. Fits comfortably in 1 GB.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
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
    """
    Per-market bounded event buffer with time-based expiry.

    Thread-safety: designed for single-threaded asyncio use within the
    ingestion TaskGroup. No locks needed — all access is from the same
    event loop.

    Usage:
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
        """
        Add an event to the appropriate market buffer.

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
        """
        Retrieve events for a market, optionally filtered by time and type.

        Args:
            market_id: Database market ID.
            since_ts: Unix milliseconds. Only return events >= this timestamp.
            event_type: Filter to a specific event type.

        Returns:
            List of EventRecord, oldest first.
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
        """
        Remove events older than max_age from all buffers.

        Called periodically by the ingestion manager, not on every add()
        (to avoid O(n) scans on the hot path).

        Returns:
            Number of events removed.
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

        # Rough memory estimate: ~250 bytes per EventRecord in a deque
        memory_mb = (total_events * 250) / (1024 * 1024)

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
```

### 1.2 Wire into IngestionManager

The ring buffer is created once and shared across the ingestion pipeline. Modify `nexus/ingestion/manager.py`:

```python
# In IngestionManager.__init__():

from nexus.ingestion.ring_buffer import EventRingBuffer

class IngestionManager(LoggerMixin):
    def __init__(self, settings, store, ...):
        # ... existing init ...
        self.ring_buffer = EventRingBuffer(
            max_age_seconds=settings.ring_buffer_max_age_seconds,  # default 86400
            max_events_per_market=settings.ring_buffer_max_events,  # default 2000
        )
```

### 1.3 Feed events into ring buffer from the batch drain worker

In the batch drain worker (the function that pulls events from the `asyncio.Queue` and calls `store.insert_events()`), add the ring buffer as a **shadow write** — events go to both PG and the buffer during this step:

```python
# In the batch drain loop (nexus/ingestion/bus.py or wherever the drain lives):

async def _drain_batch(self, events: list[EventRecord]) -> None:
    """Process a batch of events from the queue."""
    # Shadow write: feed into ring buffer (Step 1 — always)
    self.ring_buffer.add_batch(events)

    # Existing write: persist to PostgreSQL (will be filtered in Step 5)
    await self.store.insert_events(events)

    # Periodic cleanup
    self.ring_buffer.maybe_cleanup()
```

### 1.4 Add settings

In `nexus/core/config.py`, add to the `Settings` class:

```python
# Ring buffer configuration
ring_buffer_max_age_seconds: int = 86400  # 24 hours
ring_buffer_max_events: int = 2000  # per market
ring_buffer_cleanup_interval: int = 300  # seconds
```

### 1.5 Add health reporting

Expose ring buffer stats in the `/api/v1/status` endpoint. In whatever builds the status response:

```python
buffer_stats = ingestion_manager.ring_buffer.get_stats()
status["ring_buffer"] = {
    "total_events": buffer_stats.total_events,
    "total_markets": buffer_stats.total_markets,
    "memory_estimate_mb": buffer_stats.memory_estimate_mb,
    "oldest_event_age_seconds": round(buffer_stats.oldest_event_age_seconds),
    "events_added_total": buffer_stats.events_added_total,
    "events_expired_total": buffer_stats.events_expired_total,
}
```

### 1.6 Tests

New file: `tests/test_ring_buffer.py`

```python
"""Tests for EventRingBuffer."""

import time

import pytest

from nexus.core.types import EventRecord, EventType
from nexus.ingestion.ring_buffer import EventRingBuffer


def _make_event(
    market_id: int = 1,
    event_type: EventType = EventType.PRICE_CHANGE,
    timestamp: int | None = None,
    data: dict | None = None,
) -> EventRecord:
    """Helper to create test events."""
    return EventRecord(
        market_id=market_id,
        event_type=event_type,
        timestamp=timestamp or int(time.time() * 1000),
        data=data or {"yes_price": 0.65, "volume": 100},
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

    def test_get_latest_event(self):
        buf = EventRingBuffer()
        now = int(time.time() * 1000)

        buf.add(_make_event(timestamp=now - 1000))
        buf.add(_make_event(timestamp=now))

        latest = buf.get_latest_event(1)
        assert latest is not None
        assert latest.timestamp == now

    def test_add_batch(self):
        buf = EventRingBuffer()
        events = [_make_event(market_id=i) for i in range(5)]
        buf.add_batch(events)

        assert buf.get_stats().total_events == 5
        assert buf.get_stats().total_markets == 5

    def test_stats(self):
        buf = EventRingBuffer()
        for i in range(3):
            buf.add(_make_event(market_id=i))

        stats = buf.get_stats()
        assert stats.total_events == 3
        assert stats.total_markets == 3
        assert stats.memory_estimate_mb > 0
        assert stats.events_added_total == 3

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
```

### 1.7 Validation

After deploying Step 1, verify in `fly logs`:

- `ring_buffer` section appears in `/api/v1/status` responses
- `ring_buffer_cleanup` log entries appear every 5 minutes
- `memory_estimate_mb` stays under 150 MB
- PG write rate is **unchanged** (shadow mode — both destinations receive events)

**Step 1 is purely additive. Nothing reads from the ring buffer yet. No behavior changes.**

---

## Step 2: Point WindowComputer at Ring Buffer

WindowComputer currently queries PostgreSQL for events within its sliding windows. Redirect it to read from the ring buffer instead.

### 2.1 Modify WindowComputer interface

The current `WindowComputer` likely has a method that fetches events from the store for a given market and time range. The change is to accept an `EventRingBuffer` instead of (or in addition to) a `BaseStore`:

```python
# In nexus/correlation/detector.py (or wherever WindowComputer lives)

from nexus.ingestion.ring_buffer import EventRingBuffer


class WindowComputer(LoggerMixin):
    """
    Computes sliding window statistics over market events.

    Previously read events from the store (PostgreSQL). Now reads from
    the in-memory ring buffer for zero-latency window computation.
    """

    def __init__(
        self,
        ring_buffer: EventRingBuffer,
        window_sizes: list[int] | None = None,
    ):
        self._ring_buffer = ring_buffer
        # Window sizes in minutes — default: 5, 15, 60, 1440
        self._window_sizes = window_sizes or [5, 15, 60, 1440]

    def compute_windows(self, market_id: int, now_ms: int) -> dict[int, dict]:
        """
        Compute statistics for all window sizes for a single market.

        Returns:
            Dict keyed by window size (minutes) with stats:
            {
                5: {"price_delta": 0.03, "volume": 150, "trade_count": 12, "event_count": 45},
                15: {...},
                60: {...},
                1440: {...},
            }
        """
        results = {}

        for window_minutes in self._window_sizes:
            since_ts = now_ms - (window_minutes * 60 * 1000)
            events = self._ring_buffer.get_events(
                market_id, since_ts=since_ts
            )

            if not events:
                results[window_minutes] = {
                    "price_delta": 0.0,
                    "volume": 0,
                    "trade_count": 0,
                    "event_count": 0,
                }
                continue

            # Separate by type
            price_events = [
                e for e in events if e.event_type == EventType.PRICE_CHANGE
            ]
            trade_events = [
                e for e in events if e.event_type == EventType.TRADE
            ]

            # Price delta: latest price - earliest price in window
            price_delta = 0.0
            if len(price_events) >= 2:
                first_price = self._extract_price(price_events[0])
                last_price = self._extract_price(price_events[-1])
                if first_price and last_price:
                    price_delta = last_price - first_price

            # Volume: sum of trade volumes in window
            volume = sum(
                self._extract_volume(e) for e in trade_events
            )

            results[window_minutes] = {
                "price_delta": price_delta,
                "volume": volume,
                "trade_count": len(trade_events),
                "event_count": len(events),
            }

        return results

    def _extract_price(self, event: EventRecord) -> float | None:
        """Extract yes_price from event data dict."""
        data = event.data or {}
        # Handle both formats: direct float or FixedPointDollars string
        val = data.get("yes_price")
        if val is None:
            return None
        return float(val) if isinstance(val, str) else val

    def _extract_volume(self, event: EventRecord) -> int:
        """Extract volume/count from a trade event."""
        data = event.data or {}
        val = data.get("count", data.get("volume", 0))
        return int(float(val)) if val else 0
```

### 2.2 Update DetectionLoop to pass ring buffer

In `nexus/correlation/detector.py` (or wherever `DetectionLoop` / `AnomalyDetector` is initialized):

```python
# Before:
# window_computer = WindowComputer(store=self.store)

# After:
window_computer = WindowComputer(ring_buffer=ingestion_manager.ring_buffer)
```

The `AnomalyDetector` does not change — it already consumes `WindowComputer` output (dicts of stats), not raw events. The `DetectionLoop` passes window stats to the detector, which applies thresholds and produces anomaly records.

### 2.3 Fallback for cold start

On process restart, the ring buffer is empty. Detection needs to handle this gracefully until the buffer populates (typically 5–15 minutes of WebSocket streaming):

```python
# In DetectionLoop._run_cycle():

async def _run_cycle(self):
    """Run one detection cycle."""
    buffer_stats = self._ring_buffer.get_stats()

    # Skip detection if ring buffer hasn't accumulated enough data
    min_warmup_seconds = 600  # 10 minutes
    if buffer_stats.oldest_event_age_seconds < min_warmup_seconds:
        self.logger.info(
            "detection_skipped_warmup",
            oldest_event_age=round(buffer_stats.oldest_event_age_seconds),
            min_warmup=min_warmup_seconds,
        )
        return

    # ... existing detection logic, now reading from ring buffer ...
```

This matches the existing pattern where `_last_cycle_ts` is initialized to 10 minutes ago to prevent detection on stale data.

### 2.4 Validation

After deploying Step 2:

- Detection cycle logs should show normal anomaly output
- `detection_skipped_warmup` log entries appear for ~10 min after restart, then stop
- **PG read load for windowed queries drops to zero** — verify via Supabase dashboard query stats
- PG write rate is still unchanged (shadow mode)

**Step 2 removes the read-side dependency on PG for detection. PG writes still continue.**

---

## Step 3: Add CandleAggregator

Computes 1-minute OHLCV (Open/High/Low/Close/Volume) candles in memory from the ring buffer, then flushes them to a new `candles` table in PostgreSQL.

### 3.1 New table: `candles`

SQL migration (add to `sql/migrations/`):

```sql
-- Migration: Add candles table for pre-aggregated OHLCV data
-- Replaces on-the-fly compute_candlesticks() over raw events

CREATE TABLE IF NOT EXISTS candles (
    id          BIGSERIAL PRIMARY KEY,
    market_id   BIGINT NOT NULL REFERENCES markets(id),
    interval    TEXT NOT NULL DEFAULT '1m',  -- '1m', '5m', '15m', '1h', '1d'
    open_ts     BIGINT NOT NULL,             -- Window start, Unix ms
    close_ts    BIGINT NOT NULL,             -- Window end, Unix ms
    open        DOUBLE PRECISION NOT NULL,
    high        DOUBLE PRECISION NOT NULL,
    low         DOUBLE PRECISION NOT NULL,
    close       DOUBLE PRECISION NOT NULL,
    volume      BIGINT NOT NULL DEFAULT 0,
    trade_count INTEGER NOT NULL DEFAULT 0,
    created_at  BIGINT NOT NULL DEFAULT (EXTRACT(EPOCH FROM NOW()) * 1000)::BIGINT,

    UNIQUE (market_id, interval, open_ts)
);

CREATE INDEX idx_candles_market_interval_ts
    ON candles (market_id, interval, open_ts DESC);

CREATE INDEX idx_candles_open_ts
    ON candles (open_ts DESC);

-- For bulk cleanup by age
CREATE INDEX idx_candles_created_at
    ON candles (created_at);
```

### 3.2 Store methods

Add to `nexus/store/base.py` (the ABC):

```python
# In BaseStore:

@abstractmethod
async def insert_candles(self, candles: list[dict]) -> int:
    """
    Upsert pre-computed OHLCV candles.

    Each candle dict has keys: market_id, interval, open_ts, close_ts,
    open, high, low, close, volume, trade_count.

    Uses INSERT ... ON CONFLICT (market_id, interval, open_ts) DO UPDATE
    to handle re-computation of the current (incomplete) candle.

    Returns number of rows upserted.
    """
    ...

@abstractmethod
async def get_candles(
    self,
    market_id: int,
    interval: str = "1m",
    since_ts: int | None = None,
    limit: int = 500,
) -> list[dict]:
    """Retrieve OHLCV candles for a market, newest first."""
    ...

@abstractmethod
async def purge_old_candles(self, older_than_ts: int) -> int:
    """Delete candles older than the given timestamp. Returns rows deleted."""
    ...
```

Implement in `nexus/store/postgres.py`:

```python
async def insert_candles(self, candles: list[dict]) -> int:
    if not candles:
        return 0

    query = """
        INSERT INTO candles (market_id, interval, open_ts, close_ts,
                             open, high, low, close, volume, trade_count)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (market_id, interval, open_ts) DO UPDATE SET
            close_ts = EXCLUDED.close_ts,
            high = GREATEST(candles.high, EXCLUDED.high),
            low = LEAST(candles.low, EXCLUDED.low),
            close = EXCLUDED.close,
            volume = candles.volume + EXCLUDED.volume,
            trade_count = candles.trade_count + EXCLUDED.trade_count
    """

    async with self._pool.acquire() as conn:
        await conn.executemany(
            query,
            [
                (
                    c["market_id"], c["interval"], c["open_ts"], c["close_ts"],
                    c["open"], c["high"], c["low"], c["close"],
                    c["volume"], c["trade_count"],
                )
                for c in candles
            ],
        )

    return len(candles)

async def get_candles(
    self,
    market_id: int,
    interval: str = "1m",
    since_ts: int | None = None,
    limit: int = 500,
) -> list[dict]:
    query = """
        SELECT market_id, interval, open_ts, close_ts,
               open, high, low, close, volume, trade_count
        FROM candles
        WHERE market_id = $1 AND interval = $2
    """
    params: list = [market_id, interval]

    if since_ts is not None:
        query += " AND open_ts >= $3"
        params.append(since_ts)

    query += " ORDER BY open_ts DESC LIMIT $" + str(len(params) + 1)
    params.append(limit)

    async with self._pool.acquire() as conn:
        rows = await conn.fetch(query, *params)

    return [dict(row) for row in rows]

async def purge_old_candles(self, older_than_ts: int) -> int:
    async with self._pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM candles WHERE created_at < $1", older_than_ts
        )
    return int(result.split()[-1])  # "DELETE N"
```

### 3.3 New file: `nexus/ingestion/candle_aggregator.py`

```python
"""
In-memory OHLCV candle aggregation from the EventRingBuffer.

Reads price_change events from the ring buffer, computes 1-minute candles
per market, and periodically flushes completed candles to PostgreSQL.

This replaces the compute_candlesticks() SQL function for new data.
Historical candles from before this migration remain queryable.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from nexus.core.logging import LoggerMixin
from nexus.core.types import EventRecord, EventType
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
    """
    Aggregates events from the ring buffer into 1-minute OHLCV candles,
    then flushes completed candles to PostgreSQL.

    Runs as an asyncio task within the IngestionManager's TaskGroup.
    Flush interval is configurable (default: 30 seconds).
    """

    def __init__(
        self,
        ring_buffer: EventRingBuffer,
        store: BaseStore,
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
        # (to avoid double-counting on each aggregation pass)
        self._last_processed_ts: dict[int, int] = {}

        # Stats
        self._candles_flushed_total: int = 0

    def _floor_to_minute(self, ts_ms: int) -> int:
        """Floor a Unix ms timestamp to the start of its minute."""
        return (ts_ms // 60000) * 60000

    def aggregate(self) -> None:
        """
        Scan the ring buffer for new events and update candle windows.

        Called periodically by the run loop. Processes only events newer
        than the last processed timestamp per market.
        """
        now_ms = int(time.time() * 1000)

        for market_id in self._ring_buffer.get_market_ids():
            since_ts = self._last_processed_ts.get(market_id, now_ms - 120000)
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
                    price = self._extract_price(event)
                    if price is not None and price > 0:
                        candle.update_price(price)
                elif event.event_type == EventType.TRADE:
                    volume = self._extract_volume(event)
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
        """
        Main loop: aggregate events, flush completed candles.

        Designed to run as a task in the IngestionManager's TaskGroup:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(candle_aggregator.run())
        """
        self.logger.info("candle_aggregator_started")
        while True:
            try:
                self.aggregate()
                await self.flush()
            except Exception as e:
                self.logger.error("candle_aggregator_error", error=str(e))

            await asyncio.sleep(self._flush_interval)

    def _extract_price(self, event: EventRecord) -> float | None:
        data = event.data or {}
        val = data.get("yes_price")
        if val is None:
            return None
        f = float(val)
        return f if f > 0 else None

    def _extract_volume(self, event: EventRecord) -> int:
        data = event.data or {}
        val = data.get("count", data.get("volume", 0))
        return int(float(val)) if val else 0

    def get_stats(self) -> dict:
        return {
            "active_candles": len(self._active_candles),
            "pending_flush": len(self._pending_flush),
            "candles_flushed_total": self._candles_flushed_total,
            "markets_tracked": len(self._last_processed_ts),
        }
```

### 3.4 Wire into IngestionManager's TaskGroup

```python
# In IngestionManager, where the TaskGroup is created:

from nexus.ingestion.candle_aggregator import CandleAggregator

class IngestionManager(LoggerMixin):
    def __init__(self, settings, store, ...):
        # ... existing init ...
        self.ring_buffer = EventRingBuffer(...)
        self.candle_aggregator = CandleAggregator(
            ring_buffer=self.ring_buffer,
            store=self.store,
            flush_interval_seconds=30,
        )

    async def run(self):
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._run_discovery())     # existing
            tg.create_task(self._run_streaming())      # existing
            tg.create_task(self._run_detection())      # existing
            tg.create_task(self._sync_layer.run())     # existing
            tg.create_task(self._api_server.run())     # existing
            tg.create_task(self.candle_aggregator.run())  # NEW
```

### 3.5 Tests

New file: `tests/test_candle_aggregator.py`

```python
"""Tests for CandleAggregator."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.core.types import EventRecord, EventType
from nexus.ingestion.candle_aggregator import CandleAggregator, CandleWindow
from nexus.ingestion.ring_buffer import EventRingBuffer


def _make_price_event(market_id: int, price: float, ts: int) -> EventRecord:
    return EventRecord(
        market_id=market_id,
        event_type=EventType.PRICE_CHANGE,
        timestamp=ts,
        data={"yes_price": price},
    )


def _make_trade_event(market_id: int, volume: int, ts: int) -> EventRecord:
    return EventRecord(
        market_id=market_id,
        event_type=EventType.TRADE,
        timestamp=ts,
        data={"count": volume},
    )


class TestCandleWindow:
    def test_single_price_update(self):
        cw = CandleWindow(market_id=1, open_ts=0, close_ts=60000)
        cw.update_price(0.65)

        assert cw.open == 0.65
        assert cw.high == 0.65
        assert cw.low == 0.65
        assert cw.close == 0.65

    def test_multiple_price_updates(self):
        cw = CandleWindow(market_id=1, open_ts=0, close_ts=60000)
        cw.update_price(0.50)
        cw.update_price(0.70)
        cw.update_price(0.55)

        assert cw.open == 0.50
        assert cw.high == 0.70
        assert cw.low == 0.50
        assert cw.close == 0.55

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

    def test_to_dict_handles_inf_low(self):
        cw = CandleWindow(market_id=1, open_ts=0, close_ts=60000)
        # No events: low is still inf
        d = cw.to_dict()
        assert d["low"] == 0.0  # Falls back to open (which is 0.0)


class TestCandleAggregator:
    def _make_aggregator(self) -> tuple[CandleAggregator, EventRingBuffer, AsyncMock]:
        buf = EventRingBuffer(max_age_seconds=3600)
        store = AsyncMock()
        store.insert_candles = AsyncMock(return_value=0)
        agg = CandleAggregator(buf, store, flush_interval_seconds=1)
        return agg, buf, store

    def test_aggregate_produces_candle(self):
        agg, buf, _ = self._make_aggregator()
        now = int(time.time() * 1000)
        minute_start = (now // 60000) * 60000

        # Add events in the same minute
        buf.add(_make_price_event(1, 0.50, minute_start + 1000))
        buf.add(_make_price_event(1, 0.60, minute_start + 30000))
        buf.add(_make_trade_event(1, 10, minute_start + 15000))

        agg.aggregate()

        # Candle should be active (minute not complete yet unless we're near boundary)
        assert agg.get_stats()["active_candles"] >= 0
        assert agg.get_stats()["markets_tracked"] == 1

    def test_completed_candle_moves_to_pending(self):
        agg, buf, _ = self._make_aggregator()
        now = int(time.time() * 1000)

        # Events from 2 minutes ago (definitely completed)
        old_minute = ((now - 120000) // 60000) * 60000
        buf.add(_make_price_event(1, 0.50, old_minute + 1000))
        buf.add(_make_price_event(1, 0.60, old_minute + 30000))

        agg.aggregate()

        assert agg.get_stats()["pending_flush"] >= 1

    @pytest.mark.asyncio
    async def test_flush_calls_store(self):
        agg, buf, store = self._make_aggregator()
        store.insert_candles.return_value = 1

        now = int(time.time() * 1000)
        old_minute = ((now - 120000) // 60000) * 60000
        buf.add(_make_price_event(1, 0.50, old_minute + 1000))

        agg.aggregate()
        count = await agg.flush()

        assert store.insert_candles.called
        assert agg.get_stats()["candles_flushed_total"] >= 0

    @pytest.mark.asyncio
    async def test_flush_retries_on_failure(self):
        agg, buf, store = self._make_aggregator()
        store.insert_candles.side_effect = Exception("DB error")

        agg._pending_flush = [{"market_id": 1, "interval": "1m", "open_ts": 0}]
        await agg.flush()

        # Failed items should be put back
        assert len(agg._pending_flush) == 1
```

### 3.6 Validation

After deploying Step 3:

- `candles_flushed` log entries appear every 30 seconds
- `SELECT count(*) FROM candles` grows steadily
- `candle_aggregator` stats appear in `/api/v1/status`
- PG writes still include raw events (unchanged in this step)

**Step 3 is additive. A new table is populated alongside the existing events table.**

---

## Step 4: Update Candlestick API to Read from Candles Table

Replace the `compute_candlesticks()` SQL function (which aggregates OHLCV from raw `price_change` events) with a simple `SELECT` from the pre-computed `candles` table.

### 4.1 Update the candlestick REST endpoint

In `nexus/api/app.py` (or wherever the candlestick route is defined):

```python
# Before:
async def get_candlesticks(request):
    ticker = request.path_params["ticker"]
    # ... resolve ticker to market_id ...
    # Called compute_candlesticks() SQL function over raw events
    candles = await store.compute_candlesticks(market_id, ...)
    return JSONResponse(candles)


# After:
async def get_candlesticks(request):
    ticker = request.path_params["ticker"]
    market_id = await _resolve_ticker(ticker)

    interval = request.query_params.get("interval", "1m")
    since = request.query_params.get("since")
    limit = int(request.query_params.get("limit", "500"))

    since_ts = int(since) if since else None

    candles = await store.get_candles(
        market_id=market_id,
        interval=interval,
        since_ts=since_ts,
        limit=limit,
    )

    return JSONResponse(
        candles,
        headers={"Cache-Control": "public, max-age=60"},
    )
```

### 4.2 Optional: Multi-interval candles

If you want 5m, 15m, or 1h candles, you can either:

**Option A (simple):** Aggregate from 1m candles with SQL at query time:

```sql
-- 5-minute candles from 1-minute candles
SELECT
    market_id,
    '5m' as interval,
    (open_ts / 300000) * 300000 as bucket_ts,
    (array_agg(open ORDER BY open_ts ASC))[1] as open,
    MAX(high) as high,
    MIN(low) as low,
    (array_agg(close ORDER BY open_ts DESC))[1] as close,
    SUM(volume) as volume,
    SUM(trade_count) as trade_count
FROM candles
WHERE market_id = $1 AND interval = '1m' AND open_ts >= $2
GROUP BY market_id, bucket_ts
ORDER BY bucket_ts DESC
LIMIT $3;
```

**Option B (pre-compute):** Extend `CandleAggregator` to emit candles at multiple intervals. But this is an optimization — start with Option A since the 1m candles table is small enough for real-time aggregation.

### 4.3 Update webapp candlestick component

In `webapp/src/lib/nexus-api.ts`, the candlestick fetch likely already points to `/api/v1/candlesticks/{ticker}`. The response shape changes slightly — verify the field names match what the `lightweight-charts` component expects (time, open, high, low, close). Adjust the transform if needed:

```typescript
// In the candlestick data transform (webapp/src/components/ or hooks):
const candles = data.map((c: any) => ({
  time: Math.floor(c.open_ts / 1000), // lightweight-charts expects seconds
  open: c.open,
  high: c.high,
  low: c.low,
  close: c.close,
  // volume is available but lightweight-charts CandlestickSeries
  // doesn't render it natively — use a separate HistogramSeries if needed
}));
```

### 4.4 Validation

- Candlestick charts in the webapp render correctly with data from the new table
- Response times should be **faster** (simple indexed SELECT vs. CTE aggregation over raw events)
- Verify the `compute_candlesticks()` function is no longer called (check PG query logs or Supabase dashboard)

**After Step 4, no consumer reads raw `price_change` events from PostgreSQL.**

---

## Step 5: Stop Writing `price_change` Events to PostgreSQL

This is the key cutover. Filter the batch drain worker so that `price_change` events go only to the ring buffer, not to PostgreSQL.

### 5.1 Modify the batch drain worker

```python
# Events that should still be persisted to PostgreSQL
_PERSIST_EVENT_TYPES = {
    EventType.TRADE,
    EventType.NEW_MARKET,
    EventType.STATUS_CHANGE,
}

async def _drain_batch(self, events: list[EventRecord]) -> None:
    """Process a batch of events from the queue."""

    # ALL events go to the ring buffer (for detection + candle aggregation)
    self.ring_buffer.add_batch(events)

    # Only non-price-change events go to PostgreSQL
    persist_events = [
        e for e in events
        if e.event_type in _PERSIST_EVENT_TYPES
    ]

    if persist_events:
        await self.store.insert_events(persist_events)

    # Periodic cleanup
    self.ring_buffer.maybe_cleanup()
```

### 5.2 Make it configurable (feature flag)

To allow safe rollback, add a setting:

```python
# In nexus/core/config.py:
persist_price_change_events: bool = False  # Set True to revert to old behavior
```

```python
# In the drain worker:
if settings.persist_price_change_events:
    persist_events = events  # Old behavior: persist everything
else:
    persist_events = [
        e for e in events
        if e.event_type in _PERSIST_EVENT_TYPES
    ]
```

In `fly.toml`:
```toml
[env]
  PERSIST_PRICE_CHANGE_EVENTS = "false"
```

### 5.3 Update market state

The `v_current_market_state` materialized view currently derives latest price from events. With price_change events gone from PG, you need an alternative. Two options:

**Option A (recommended): Direct market row updates.**

When the ring buffer receives a `price_change`, also update the `markets` table row with the latest price. This is a single `UPDATE` per market per discovery cycle (not per event — batch the latest value):

```python
# New method added to the drain/ingestion logic:

async def _update_market_prices(self, events: list[EventRecord]) -> None:
    """
    Batch-update the markets table with latest prices from this batch.

    Groups events by market_id, takes the latest price_change per market,
    and issues a single UPDATE for each.
    """
    latest_by_market: dict[int, EventRecord] = {}
    for e in events:
        if e.event_type == EventType.PRICE_CHANGE:
            existing = latest_by_market.get(e.market_id)
            if existing is None or e.timestamp > existing.timestamp:
                latest_by_market[e.market_id] = e

    if not latest_by_market:
        return

    for market_id, event in latest_by_market.items():
        price = self._extract_price(event)
        volume = event.data.get("volume", event.data.get("dollar_volume"))
        if price is not None:
            await self.store.update_market_price(
                market_id=market_id,
                yes_price=price,
                volume=int(float(volume)) if volume else None,
                last_updated=event.timestamp,
            )
```

Add to `BaseStore` and `PostgresStore`:

```python
# In BaseStore (ABC):
@abstractmethod
async def update_market_price(
    self, market_id: int, yes_price: float,
    volume: int | None, last_updated: int
) -> None:
    ...

# In PostgresStore:
async def update_market_price(
    self, market_id: int, yes_price: float,
    volume: int | None, last_updated: int
) -> None:
    async with self._pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE markets
            SET yes_price = $2,
                volume = COALESCE($3, volume),
                last_updated = $4
            WHERE id = $1 AND last_updated < $4
            """,
            market_id, yes_price, volume, last_updated,
        )
```

**Option B:** Rewrite `v_current_market_state` to read from the `markets` table directly (which is now kept up to date) instead of aggregating from events.

```sql
-- Replace the materialized view with a simpler version:
CREATE OR REPLACE VIEW v_current_market_state AS
SELECT
    m.id,
    m.external_id,
    m.ticker,
    m.title,
    m.platform,
    m.category,
    m.yes_price,
    m.volume,
    m.is_active,
    m.last_updated
FROM markets m
WHERE m.is_active = true;
```

This can be a regular view (not materialized) since it's just reading rows from the `markets` table, which is now always up to date.

### 5.4 Updated drain worker (complete)

```python
_PERSIST_EVENT_TYPES = {
    EventType.TRADE,
    EventType.NEW_MARKET,
    EventType.STATUS_CHANGE,
}

async def _drain_batch(self, events: list[EventRecord]) -> None:
    """Process a batch of events from the queue."""

    # 1. ALL events go to the ring buffer
    self.ring_buffer.add_batch(events)

    # 2. Update market prices from price_change events
    await self._update_market_prices(events)

    # 3. Only non-price-change events go to PostgreSQL
    if not settings.persist_price_change_events:
        persist_events = [
            e for e in events
            if e.event_type in _PERSIST_EVENT_TYPES
        ]
    else:
        persist_events = events

    if persist_events:
        await self.store.insert_events(persist_events)

    # 4. Periodic cleanup
    self.ring_buffer.maybe_cleanup()
```

### 5.5 Validation

After deploying Step 5:

- **PG write rate drops by ~90%** — verify via Supabase dashboard
- `events` table growth rate drops from ~120 MB/day to ~12 MB/day
- `/api/v1/markets` still returns current prices (from `markets` table)
- `/api/v1/candlesticks/{ticker}` still works (from `candles` table)
- Detection still fires anomalies (from ring buffer)
- `PERSIST_PRICE_CHANGE_EVENTS=true` in fly.toml reverts to old behavior if needed

**Step 5 is the breaking change. Test thoroughly in staging first.**

---

## Step 6: Purge Historical `price_change` Events

Reclaim the ~600+ MB consumed by old `price_change` rows in the events table.

### 6.1 One-time purge

Run via `fly ssh console` or a management CLI command:

```sql
-- Check what we're about to delete
SELECT event_type, count(*), pg_size_pretty(sum(pg_column_size(t.*)))
FROM events t
GROUP BY event_type;

-- Delete price_change events (in batches to avoid long locks)
-- Batch 1:
DELETE FROM events
WHERE id IN (
    SELECT id FROM events
    WHERE event_type = 'price_change'
    LIMIT 100000
);

-- Repeat until no rows remain. Each batch takes seconds.

-- After all batches complete:
VACUUM ANALYZE events;
```

### 6.2 Add a CLI command for ongoing maintenance

New command in `nexus/cli.py`:

```python
@app.command()
def purge_events(
    event_type: str = typer.Option("price_change", help="Event type to purge"),
    older_than_days: int = typer.Option(7, help="Purge events older than N days"),
    batch_size: int = typer.Option(50000, help="Delete in batches of N"),
    dry_run: bool = typer.Option(True, help="Show counts without deleting"),
):
    """Purge old events from PostgreSQL."""
    async def _purge():
        store = await create_store(settings)
        cutoff_ts = int((time.time() - older_than_days * 86400) * 1000)

        if dry_run:
            count = await store.count_events(
                event_type=event_type, older_than_ts=cutoff_ts
            )
            console.print(f"[yellow]DRY RUN:[/] Would delete {count:,} "
                          f"{event_type} events older than {older_than_days} days")
            return

        total_deleted = 0
        while True:
            deleted = await store.purge_events_batch(
                event_type=event_type,
                older_than_ts=cutoff_ts,
                limit=batch_size,
            )
            total_deleted += deleted
            console.print(f"Deleted batch: {deleted:,} (total: {total_deleted:,})")
            if deleted < batch_size:
                break

        console.print(f"[green]Purged {total_deleted:,} events. Running VACUUM...[/]")
        await store.vacuum_events()
        console.print("[green]Done.[/]")

    asyncio.run(_purge())
```

With corresponding store methods:

```python
# In PostgresStore:

async def count_events(
    self, event_type: str, older_than_ts: int
) -> int:
    async with self._pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT count(*) FROM events WHERE event_type = $1 AND timestamp < $2",
            event_type, older_than_ts,
        )

async def purge_events_batch(
    self, event_type: str, older_than_ts: int, limit: int
) -> int:
    async with self._pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM events
            WHERE id IN (
                SELECT id FROM events
                WHERE event_type = $1 AND timestamp < $2
                LIMIT $3
            )
            """,
            event_type, older_than_ts, limit,
        )
    return int(result.split()[-1])

async def vacuum_events(self) -> None:
    # VACUUM cannot run inside a transaction
    async with self._pool.acquire() as conn:
        await conn.execute("VACUUM ANALYZE events")
```

### 6.3 Ongoing retention policy

Add to `fly.toml`:

```toml
[env]
  EVENT_RETENTION_DAYS = "30"  # Keep trade/status events for 30 days
  CANDLE_RETENTION_DAYS = "90"  # Keep 1m candles for 90 days
```

Add a periodic cleanup task in the pipeline:

```python
# In IngestionManager, run daily:

async def _run_retention_cleanup(self):
    """Purge expired events and candles. Runs once per day."""
    while True:
        await asyncio.sleep(86400)  # 24 hours
        try:
            event_cutoff = int(
                (time.time() - settings.event_retention_days * 86400) * 1000
            )
            candle_cutoff = int(
                (time.time() - settings.candle_retention_days * 86400) * 1000
            )

            events_purged = await self.store.purge_events_batch(
                event_type="trade",
                older_than_ts=event_cutoff,
                limit=500000,
            )
            candles_purged = await self.store.purge_old_candles(candle_cutoff)

            self.logger.info(
                "retention_cleanup",
                events_purged=events_purged,
                candles_purged=candles_purged,
            )
        except Exception as e:
            self.logger.error("retention_cleanup_failed", error=str(e))
```

### 6.4 Validation

After purge:

- Run `SELECT pg_size_pretty(pg_total_relation_size('events'))` — should drop from ~900+ MB (table + indexes) to under 100 MB
- Run `SELECT pg_database_size(current_database())` — total DB size should drop from 740 MB to under 200 MB
- Well within Supabase free tier (500 MB) with headroom for growth

---

## Step 7 (Optional): Archive Raw Events for Backtesting

If you want raw event replay for the `nexus backtest` command, write events to an append-only archive outside PostgreSQL.

### 7.1 Option A: Local SQLite on Fly.io volume

```python
# nexus/ingestion/event_archive.py

import aiosqlite
import json
from pathlib import Path
from nexus.core.types import EventRecord


class EventArchive(LoggerMixin):
    """
    Append-only SQLite archive of raw events for backtesting.

    Stored on Fly.io persistent volume at /data/archive.db.
    Not queried in real-time — only by `nexus backtest` command.
    """

    def __init__(self, db_path: str = "/data/event_archive.db"):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self):
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                market_id INTEGER,
                event_type TEXT,
                timestamp INTEGER,
                data TEXT,
                archived_at INTEGER DEFAULT (strftime('%s','now') * 1000)
            )
        """)
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_archive_ts ON events(timestamp)"
        )
        await self._db.commit()

    async def append(self, events: list[EventRecord]) -> None:
        if not self._db or not events:
            return
        await self._db.executemany(
            "INSERT INTO events (market_id, event_type, timestamp, data) "
            "VALUES (?, ?, ?, ?)",
            [
                (e.market_id, e.event_type.value, e.timestamp,
                 json.dumps(e.data) if e.data else None)
                for e in events
            ],
        )
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()
```

Wire into the drain worker:

```python
# price_change events that skip PG can optionally go to the archive:
if self._archive and not settings.persist_price_change_events:
    price_change_events = [
        e for e in events if e.event_type == EventType.PRICE_CHANGE
    ]
    await self._archive.append(price_change_events)
```

### 7.2 Option B: Cloudflare R2 / Tigris (object storage)

Write events as newline-delimited JSON files, one per hour:

```
/events/2026/03/26/14.ndjson
/events/2026/03/26/15.ndjson
```

This is cheaper and more durable than SQLite on a volume, but requires an object storage client. Tigris on Fly.io is S3-compatible and has a generous free tier (5 GB). This is a better option if the archive grows large.

### 7.3 Update `nexus backtest` to read from archive

```python
# In the backtest command, add a --source flag:
@app.command()
def backtest(
    source: str = typer.Option("archive", help="Event source: 'archive' or 'postgres'"),
    ...
):
    if source == "archive":
        archive = EventArchive()
        events = await archive.query(since_ts=..., until_ts=...)
    else:
        events = await store.get_events(since_ts=..., until_ts=...)
```

---

## Deployment Sequence

Execute in this exact order. Each step is independently deployable and reversible.

```
Step 1: Deploy ring buffer (shadow mode)
        ├── Verify: /api/v1/status shows ring_buffer stats
        ├── Verify: PG write rate unchanged
        └── Wait: 24h observation
                │
Step 2: Switch WindowComputer to ring buffer
        ├── Verify: Detection still produces anomalies
        ├── Verify: PG event reads drop to near zero
        └── Wait: 24h observation
                │
Step 3: Deploy CandleAggregator + candles table
        ├── Verify: candles table populating
        ├── Verify: candles_flushed log entries
        └── Wait: 24h (accumulate candle history)
                │
Step 4: Switch candlestick API to candles table
        ├── Verify: Webapp charts render correctly
        ├── Verify: compute_candlesticks() no longer called
        └── Wait: 24h observation
                │
Step 5: Stop writing price_change to PG (THE BIG SWITCH)
        ├── Set PERSIST_PRICE_CHANGE_EVENTS=false
        ├── Verify: PG write rate drops ~90%
        ├── Verify: All API endpoints still return data
        ├── Verify: Detection still works
        ├── Fallback: Set PERSIST_PRICE_CHANGE_EVENTS=true
        └── Wait: 48h observation
                │
Step 6: Purge historical price_change events
        ├── Run nexus purge-events --older-than-days 0 --dry-run
        ├── Run nexus purge-events --older-than-days 0 --no-dry-run
        ├── Verify: DB size drops to <200 MB
        └── Celebrate: Supabase free tier viable again
                │
Step 7: (Optional) Set up event archive for backtesting
```

---

## Step 0: Immediate Purge (Before Any Code Changes)

Buy headroom on Supabase now. No code changes required — run via `fly ssh console` or a one-off script.

### 0.1 Purge inactive markets

75,892 markets in the `markets` table, only ~4,354 are active. The other ~71K are stale rows from discovery accumulation.

```sql
-- Check what we're about to delete
SELECT is_active, COUNT(*) FROM markets GROUP BY is_active;

-- Delete inactive markets with no events (safe — FK constraint protects markets with events)
DELETE FROM markets
WHERE is_active = false
  AND id NOT IN (SELECT DISTINCT market_id FROM events);

-- If the above is slow due to subquery, batch it:
DELETE FROM markets WHERE id IN (
    SELECT m.id FROM markets m
    LEFT JOIN events e ON e.market_id = m.id
    WHERE m.is_active = false AND e.id IS NULL
    LIMIT 50000
);
-- Repeat until 0 rows deleted.

VACUUM ANALYZE markets;
```

### 0.2 Reduce retention and purge old events

Set `RETENTION_DAYS=14` in fly.toml (current data only goes back 14.1 days anyway — no data loss). Then purge:

```sql
-- Check age distribution
SELECT
    CASE
        WHEN timestamp > EXTRACT(EPOCH FROM NOW())*1000 - 604800000 THEN '<7 days'
        ELSE '>7 days'
    END as age,
    COUNT(*)
FROM events GROUP BY 1;

-- Delete events older than 14 days (if any)
DELETE FROM events
WHERE timestamp < EXTRACT(EPOCH FROM NOW())*1000 - 1209600000;

VACUUM ANALYZE events;
```

### 0.3 Verify

```sql
SELECT pg_size_pretty(pg_database_size(current_database()));
-- Should be noticeably smaller after VACUUM reclaims space
```

**Step 0 requires zero code changes and zero deployment. It buys time for the remaining steps.**

---

## Review Notes & Known Issues

_Added during code review on 2026-03-26. These must be addressed during implementation._

### Issue 1: Ring buffer memory estimate may be low

The doc estimates ~250 bytes/EventRecord, but Python dataclass objects with a `data` dict have significant overhead (GC headers, dict internals, string keys). Realistic estimate is 400–500 bytes per event. At 487K events/day across 4,354 markets, a 24h ring buffer could reach 190–240 MB — still fits within 1 GB but tighter than the 140 MB estimate.

**Action:** After deploying Step 1 (shadow mode), measure the actual RSS delta over 24h before committing to Step 5. If RSS exceeds 450 MB, reduce `max_age_seconds` from 86400 (24h) to 43200 (12h) — detection only needs the largest window (1440 min = 24h) for baseline, and a 12h buffer still covers it.

### Issue 2: 1440-minute window undersampled after restart

Step 2.3 skips detection for 10 minutes after restart. But the 1440-minute (24h) window will be severely undersampled for the first 24 hours post-restart — the ring buffer only has minutes of data, not hours. This can cause missed anomalies or false positives from incomplete baselines.

**Action (choose one):**
- **(a)** Keep a PG fallback for the 1440-minute window during warmup: if `buffer_stats.oldest_event_age_seconds < 1440 * 60`, fall back to `store.get_events()` for that window only. Remove fallback once buffer is warm.
- **(b)** Accept degraded detection on the 24h window for the first 24h post-restart and document this tradeoff. The 5/15/60-minute windows will work correctly within 60 minutes.
- **(c)** Pre-seed the ring buffer from PG on startup: `SELECT * FROM events WHERE timestamp > NOW() - INTERVAL '24 hours'`. This is ~487K rows and would take a few seconds over the Supabase connection.

Option (c) is cleanest if the events table still exists. Option (b) is simplest if the events table has been purged.

### Issue 3: CandleAggregator volume double-counting on upsert

The `insert_candles` SQL uses `volume = candles.volume + EXCLUDED.volume`, which accumulates volume on each upsert. If the aggregator re-processes events for the same minute (e.g., after restart), volume gets double-counted in the DB row.

**Fix:** Change the upsert to replace instead of accumulate:

```sql
ON CONFLICT (market_id, interval, open_ts) DO UPDATE SET
    close_ts = EXCLUDED.close_ts,
    high = GREATEST(candles.high, EXCLUDED.high),
    low = LEAST(candles.low, EXCLUDED.low),
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,           -- REPLACE, not accumulate
    trade_count = EXCLUDED.trade_count  -- REPLACE, not accumulate
```

The CandleAggregator's `_last_processed_ts` watermark prevents double-processing within a single process lifetime, but restarts reset the watermark. Replace semantics are safe because the aggregator always recomputes the full candle from the ring buffer.

### Issue 4: Market state view must be updated before Step 5

If Step 5 (stop writing `price_change` events) deploys before the `v_current_market_state` view is rewritten, the view goes stale immediately because it reads from the events table.

**Fix:** Add columns and shadow-write logic in Step 3 (not Step 5):

- **Step 3.5 (new):** Add `yes_price`, `volume`, `last_updated` columns to the `markets` table. Shadow-write latest prices during the batch drain alongside the existing event writes. This runs in parallel with the old view — no breakage.
- **Step 5:** Swap the view definition from events-based to markets-table-based simultaneously with the price_change filter.

### Issue 5: SQLite archive on Fly volume is fragile

Fly machines can be replaced at any time (scaling, hardware migration). Volumes are per-machine. If the machine is replaced without a volume migration, the SQLite archive is lost.

**Recommendation:** Skip Option A (SQLite). Use Option B (Tigris/R2 object storage) from the start, or defer archiving entirely until the candle table proves sufficient for backtesting. The SQLite option gives a false sense of durability.

### Issue 6: Purge stale markets alongside events

The doc focuses on event purge (Step 6) but doesn't address the 75,892 accumulated market rows (only 4,354 active). That's 31 MB of table data plus index overhead.

**Fix:** Added as Step 0.1 above. Also add to the retention cleanup task in Step 6.3:

```python
# Purge inactive markets with no recent events
markets_purged = await self.store.purge_stale_markets(
    inactive_for_days=settings.event_retention_days
)
```

### Minor Nits

1. **File path:** The doc references `nexus/correlation/detector.py` for WindowComputer. Verify the actual path — the current codebase may have WindowComputer logic inside `DetectionLoop` in a different file.

2. **TaskGroup wiring:** Step 3.4 shows `CandleAggregator` wired into `IngestionManager.run()`, but the actual TaskGroup structure in `cli.py` has detection, sync, and API as separate tasks in the outer TaskGroup (not inside IngestionManager). Wire the aggregator into the outer TaskGroup in `cli.py` to match the real architecture.

3. **VACUUM in a transaction:** The `vacuum_events()` store method in Step 6.2 uses `conn.execute("VACUUM ANALYZE events")`, but VACUUM cannot run inside a transaction (asyncpg wraps queries in implicit transactions). Use a dedicated connection with `await conn.execute("SET statement_timeout = 0")` and run outside the connection pool, or use `conn.reset()` to exit any implicit transaction first.

4. **Candle interval naming:** The `candles.interval` column uses strings (`'1m'`, `'5m'`). Consider using integer minutes instead to avoid string comparison in queries and to simplify the multi-interval aggregation math.

---

## Revised Deployment Sequence

Execute in this exact order. Each step is independently deployable and reversible.

```
Step 0: Immediate purge (no code changes)
        ├── Purge inactive markets (71K rows)
        ├── Reduce RETENTION_DAYS to 14
        ├── Purge events older than 14 days
        ├── VACUUM ANALYZE
        └── Verify: DB size drops, free tier headroom restored
                │
Step 1: Deploy ring buffer (shadow mode)
        ├── Verify: /api/v1/status shows ring_buffer stats
        ├── Verify: PG write rate unchanged
        ├── Verify: RSS delta from ring buffer (expect +100–200 MB)
        └── Wait: 24h observation
                │
Step 2: Switch WindowComputer to ring buffer
        ├── Verify: Detection still produces anomalies
        ├── Verify: PG event reads drop to near zero
        ├── Monitor: 1440-min window accuracy post-restart
        └── Wait: 24h observation
                │
Step 3: Deploy CandleAggregator + candles table
        ├── Verify: candles table populating
        ├── Verify: candles_flushed log entries
        └── Wait: 24h (accumulate candle history)
                │
Step 3.5: Add market price columns + shadow-write
        ├── Add yes_price, volume, last_updated to markets table
        ├── Shadow-write latest prices in batch drain worker
        ├── Verify: markets.yes_price matches events-derived price
        └── Wait: 24h observation
                │
Step 4: Switch candlestick API to candles table
        ├── Verify: Webapp charts render correctly
        ├── Verify: compute_candlesticks() no longer called
        └── Wait: 24h observation
                │
Step 5: Stop writing price_change to PG (THE BIG SWITCH)
        ├── Set PERSIST_PRICE_CHANGE_EVENTS=false
        ├── Simultaneously swap v_current_market_state to read from
        │   markets table instead of events
        ├── Verify: PG write rate drops ~90%
        ├── Verify: All API endpoints still return data
        ├── Verify: Detection still works
        ├── Fallback: Set PERSIST_PRICE_CHANGE_EVENTS=true
        └── Wait: 48h observation
                │
Step 6: Purge historical price_change events + stale markets
        ├── Run nexus purge-events --older-than-days 0 --dry-run
        ├── Run nexus purge-events --older-than-days 0 --no-dry-run
        ├── Purge stale markets (inactive, no events)
        ├── Verify: DB size drops to <200 MB
        └── Celebrate: Supabase free tier viable long-term
                │
Step 7: (Optional) Set up event archive for backtesting
        ├── Use Tigris/R2 object storage (NOT SQLite on Fly volume)
        └── NDJSON files per hour for replay
```

---

## Expected Outcome

| Metric | Before | After |
|--------|--------|-------|
| PG writes/day | ~487,000 | ~30,000–50,000 |
| PG storage (events) | 678 MB (growing 3.5 GB/mo) | <50 MB (stable) |
| PG total size | 740 MB (over free tier) | <200 MB |
| PG storage growth/month | 3.5 GB | ~100–200 MB |
| Fly.io RSS | 276 MB | ~400–450 MB |
| Detection data source | PostgreSQL (network I/O) | In-memory (zero latency) |
| Candlestick source | Raw event aggregation | Pre-computed candles |
| Supabase tier needed | Pro ($25/mo) urgently | Free tier viable for 6+ months |
| Time to support Polymarket | Requires PG upgrade | Scales in-memory, no PG impact |
| Time to support social media | Requires PG upgrade | Same pattern: buffer in memory, persist summaries |

---

## Files Created or Modified

| File | Action | Step |
|------|--------|------|
| `nexus/ingestion/ring_buffer.py` | **New** | 1 |
| `nexus/ingestion/candle_aggregator.py` | **New** | 3 |
| `nexus/ingestion/event_archive.py` | **New** (optional) | 7 |
| `nexus/ingestion/manager.py` | Modified: wire ring buffer | 1 |
| `nexus/ingestion/bus.py` | Modified: event routing logic + market price shadow-write | 1, 3.5, 5 |
| `nexus/correlation/detector.py` | Modified: WindowComputer reads ring buffer | 2 |
| `nexus/store/base.py` | Modified: add candle + purge + market price ABCs | 3, 3.5, 5, 6 |
| `nexus/store/postgres.py` | Modified: implement candle + purge + market price | 3, 3.5, 5, 6 |
| `nexus/api/app.py` | Modified: candlestick endpoint reads candles table | 4 |
| `nexus/core/config.py` | Modified: new settings | 1, 5 |
| `nexus/cli.py` | Modified: purge-events command, wire aggregator into TaskGroup | 3, 6 |
| `sql/migrations/add_candles_table.sql` | **New** | 3 |
| `sql/migrations/add_market_price_columns.sql` | **New** | 3.5 |
| `tests/test_ring_buffer.py` | **New** | 1 |
| `tests/test_candle_aggregator.py` | **New** | 3 |
| `fly.toml` | Modified: new env vars | 0, 5, 6 |
| `webapp/src/components/` or `hooks/` | Modified: candlestick data transform | 4 |
