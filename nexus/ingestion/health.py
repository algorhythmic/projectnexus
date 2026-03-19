"""Periodic health reporter for the ingestion pipeline.

Logs a MetricsSnapshot at configurable intervals during pipeline
operation.  Intended to run as a background task alongside the
ingestion manager.
"""

import asyncio
from pathlib import Path
from typing import Optional

from nexus.core.logging import LoggerMixin
from nexus.ingestion.metrics import MetricsCollector


def _get_rss_mb() -> Optional[float]:
    """Return current RSS in MB by reading /proc/self/status (Linux only).

    Returns None on platforms where /proc is unavailable.
    """
    try:
        status = Path("/proc/self/status").read_text()
        for line in status.splitlines():
            if line.startswith("VmRSS:"):
                kb = int(line.split()[1])
                return round(kb / 1024, 1)
    except (FileNotFoundError, OSError, ValueError):
        pass
    return None


class HealthReporter(LoggerMixin):
    """Logs pipeline health metrics on a fixed interval.

    Usage::

        reporter = HealthReporter(metrics, interval_seconds=60)
        reporter.start()
        ...
        await reporter.stop()
    """

    def __init__(
        self,
        metrics: MetricsCollector,
        interval_seconds: float = 60.0,
    ) -> None:
        self._metrics = metrics
        self._interval = interval_seconds
        self._task: Optional[asyncio.Task[None]] = None

    def start(self) -> None:
        """Launch the periodic reporting loop."""
        if self._task is not None:
            return
        self._task = asyncio.get_event_loop().create_task(self._report_loop())
        self.logger.info(
            "HealthReporter started", interval=self._interval
        )

    async def stop(self) -> None:
        """Stop the reporting loop."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.logger.info("HealthReporter stopped")

    async def _report_loop(self) -> None:
        """Main loop: take snapshot, log it, sleep."""
        while True:
            snap = self._metrics.snapshot()
            extra: dict = {}
            rss = _get_rss_mb()
            if rss is not None:
                extra["rss_mb"] = rss
            self.logger.info(
                "Pipeline health",
                uptime_s=snap.uptime_seconds,
                total_events=snap.total_events_written,
                events_per_sec=snap.events_per_second,
                ws_connected=snap.ws_connected,
                ws_uptime_s=snap.ws_uptime_seconds,
                ws_reconnects=snap.ws_reconnect_count,
                queue_depth=snap.queue_depth,
                errors=snap.error_counts,
                **extra,
            )
            await asyncio.sleep(self._interval)
