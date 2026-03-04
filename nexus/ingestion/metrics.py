"""In-memory metrics collector for stability monitoring.

Tracks events/second throughput, WebSocket connection uptime,
error counts by category, and queue depth.  All methods are
synchronous — safe to call from any coroutine in a single-threaded
asyncio event loop.
"""

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, Dict, Optional

from nexus.core.logging import LoggerMixin


class ErrorCategory(str, Enum):
    """Categorized failure modes (per spec: disconnections,
    auth token expiry, rate limit hits, data gaps)."""

    WS_DISCONNECT = "ws_disconnect"
    WS_ERROR = "ws_error"
    AUTH_TOKEN_EXPIRY = "auth_token_expiry"
    RATE_LIMIT_HIT = "rate_limit_hit"
    DISCOVERY_ERROR = "discovery_error"
    STORE_ERROR = "store_error"
    UNKNOWN = "unknown"


@dataclass
class MetricsSnapshot:
    """Point-in-time snapshot of all pipeline metrics."""

    uptime_seconds: float
    total_events_written: int
    events_per_second: float
    ws_connected: bool
    ws_uptime_seconds: float
    ws_reconnect_count: int
    queue_depth: int
    error_counts: Dict[str, int]
    timestamp: float


class MetricsCollector(LoggerMixin):
    """Centralized in-memory metrics for the ingestion pipeline.

    Usage::

        metrics = MetricsCollector()
        metrics.record_events_written(10)
        metrics.record_ws_connected()
        snap = metrics.snapshot()
    """

    def __init__(self, throughput_window: float = 60.0) -> None:
        self._start_time = time.monotonic()
        self._throughput_window = throughput_window

        # Rolling window of event write timestamps for throughput calc
        self._event_timestamps: Deque[float] = deque()
        self._total_events: int = 0

        # WebSocket connection tracking
        self._ws_connected: bool = False
        self._ws_connected_since: Optional[float] = None
        self._ws_total_uptime: float = 0.0
        self._ws_reconnect_count: int = 0

        # Queue depth gauge
        self._queue_depth: int = 0

        # Error counters by category
        self._error_counts: Dict[str, int] = {
            cat.value: 0 for cat in ErrorCategory
        }

    # -- Event tracking --

    def record_events_written(self, count: int) -> None:
        """Called after a batch is successfully written to store."""
        now = time.monotonic()
        self._total_events += count
        for _ in range(count):
            self._event_timestamps.append(now)

    def record_events_failed(self, count: int) -> None:
        """Called when a batch write fails."""
        self._error_counts[ErrorCategory.STORE_ERROR.value] += 1

    # -- WebSocket state --

    def record_ws_connected(self) -> None:
        """Called when WebSocket connection is established."""
        self._ws_connected = True
        self._ws_connected_since = time.monotonic()

    def record_ws_disconnected(self) -> None:
        """Called when WebSocket connection is lost."""
        if self._ws_connected and self._ws_connected_since is not None:
            self._ws_total_uptime += time.monotonic() - self._ws_connected_since
        self._ws_connected = False
        self._ws_connected_since = None
        self._ws_reconnect_count += 1

    # -- Error tracking --

    def record_error(self, category: ErrorCategory) -> None:
        """Increment an error counter by category."""
        self._error_counts[category.value] += 1

    # -- Queue depth --

    def update_queue_depth(self, depth: int) -> None:
        """Update the current queue depth gauge."""
        self._queue_depth = depth

    # -- Snapshot --

    def snapshot(self) -> MetricsSnapshot:
        """Return a point-in-time snapshot of all metrics."""
        now = time.monotonic()

        # Prune timestamps outside the rolling window
        cutoff = now - self._throughput_window
        while self._event_timestamps and self._event_timestamps[0] < cutoff:
            self._event_timestamps.popleft()

        # Events/second over the rolling window
        window_events = len(self._event_timestamps)
        eps = (
            window_events / self._throughput_window
            if self._throughput_window > 0
            else 0.0
        )

        # WebSocket uptime (include current session if connected)
        ws_uptime = self._ws_total_uptime
        if self._ws_connected and self._ws_connected_since is not None:
            ws_uptime += now - self._ws_connected_since

        return MetricsSnapshot(
            uptime_seconds=round(now - self._start_time, 1),
            total_events_written=self._total_events,
            events_per_second=round(eps, 2),
            ws_connected=self._ws_connected,
            ws_uptime_seconds=round(ws_uptime, 1),
            ws_reconnect_count=self._ws_reconnect_count,
            queue_depth=self._queue_depth,
            error_counts=dict(self._error_counts),
            timestamp=time.time(),
        )
