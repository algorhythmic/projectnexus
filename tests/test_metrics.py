"""Tests for the MetricsCollector."""

import time

import pytest

from nexus.ingestion.metrics import ErrorCategory, MetricsCollector, MetricsSnapshot


class TestMetricsCollector:
    def test_initial_snapshot_is_zeroed(self):
        """Fresh collector has zero events, zero errors, not connected."""
        m = MetricsCollector()
        snap = m.snapshot()
        assert snap.total_events_written == 0
        assert snap.events_per_second == 0.0
        assert snap.ws_connected is False
        assert snap.ws_uptime_seconds == 0.0
        assert snap.ws_reconnect_count == 0
        assert snap.queue_depth == 0
        assert all(v == 0 for v in snap.error_counts.values())

    def test_record_events_written(self):
        """record_events_written increments total count."""
        m = MetricsCollector()
        m.record_events_written(5)
        m.record_events_written(3)
        snap = m.snapshot()
        assert snap.total_events_written == 8

    def test_events_per_second(self):
        """events_per_second reflects recent writes within the window."""
        m = MetricsCollector(throughput_window=10.0)
        m.record_events_written(20)
        snap = m.snapshot()
        assert snap.events_per_second == 2.0  # 20 events / 10s window

    def test_ws_connected_state(self):
        """record_ws_connected sets ws_connected to True."""
        m = MetricsCollector()
        m.record_ws_connected()
        snap = m.snapshot()
        assert snap.ws_connected is True

    def test_ws_disconnect_increments_reconnect(self):
        """Disconnect increments reconnect count and clears connected."""
        m = MetricsCollector()
        m.record_ws_connected()
        m.record_ws_disconnected()
        snap = m.snapshot()
        assert snap.ws_connected is False
        assert snap.ws_reconnect_count == 1

    def test_ws_uptime_tracking(self):
        """WS uptime accumulates across connect/disconnect cycles."""
        m = MetricsCollector()
        m.record_ws_connected()
        # Simulate some elapsed time
        m._ws_connected_since = time.monotonic() - 5.0
        m.record_ws_disconnected()
        snap = m.snapshot()
        assert snap.ws_uptime_seconds >= 4.5  # allow some tolerance

    def test_error_counts_by_category(self):
        """Errors are tracked separately by category."""
        m = MetricsCollector()
        m.record_error(ErrorCategory.WS_DISCONNECT)
        m.record_error(ErrorCategory.WS_DISCONNECT)
        m.record_error(ErrorCategory.RATE_LIMIT_HIT)
        snap = m.snapshot()
        assert snap.error_counts["ws_disconnect"] == 2
        assert snap.error_counts["rate_limit_hit"] == 1
        assert snap.error_counts["store_error"] == 0

    def test_record_events_failed(self):
        """record_events_failed increments STORE_ERROR count."""
        m = MetricsCollector()
        m.record_events_failed(5)
        snap = m.snapshot()
        assert snap.error_counts["store_error"] == 1

    def test_queue_depth_update(self):
        """update_queue_depth sets the gauge value."""
        m = MetricsCollector()
        m.update_queue_depth(42)
        snap = m.snapshot()
        assert snap.queue_depth == 42

    def test_snapshot_independence(self):
        """Modifying one snapshot's error_counts doesn't affect the collector."""
        m = MetricsCollector()
        m.record_error(ErrorCategory.WS_ERROR)
        snap1 = m.snapshot()
        snap1.error_counts["ws_error"] = 999
        snap2 = m.snapshot()
        assert snap2.error_counts["ws_error"] == 1


class TestErrorCategory:
    def test_all_failure_modes_represented(self):
        """Enum covers the spec's required failure modes."""
        names = {c.value for c in ErrorCategory}
        assert "ws_disconnect" in names
        assert "auth_token_expiry" in names
        assert "rate_limit_hit" in names
        assert "discovery_error" in names
        assert "store_error" in names

    def test_enum_values_are_strings(self):
        """All values are valid strings for structured logging."""
        for cat in ErrorCategory:
            assert isinstance(cat.value, str)
            assert len(cat.value) > 0
