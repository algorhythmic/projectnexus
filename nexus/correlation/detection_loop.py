"""Periodic anomaly detection loop."""

import asyncio
import time
from typing import List, Optional

from nexus.core.logging import LoggerMixin
from nexus.core.types import WindowConfig
from nexus.correlation.detector import AnomalyDetector
from nexus.correlation.windows import WindowComputer
from nexus.store.base import BaseStore


class DetectionLoop(LoggerMixin):
    """Runs anomaly detection periodically across all active markets."""

    def __init__(
        self,
        store: BaseStore,
        window_configs: List[WindowConfig],
        interval_seconds: int = 300,
        baseline_hours: int = 24,
        expiry_hours: int = 24,
    ) -> None:
        self._store = store
        self._window_configs = window_configs
        self._interval = interval_seconds
        self._baseline_hours = baseline_hours
        self._expiry_hours = expiry_hours
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def run_once(self) -> int:
        """Run a single detection cycle. Returns anomaly count."""
        now_ms = int(time.time() * 1000)

        # Expire old anomalies first
        expiry_cutoff = now_ms - (self._expiry_hours * 3600 * 1000)
        expired = await self._store.expire_old_anomalies(expiry_cutoff)
        if expired > 0:
            self.logger.info("expired_anomalies", count=expired)

        # Get all active markets
        markets = await self._store.get_active_markets()
        market_ids = [m.id for m in markets if m.id is not None]

        if not market_ids:
            self.logger.info("detection_skip", reason="no active markets")
            return 0

        wc = WindowComputer(self._store)
        detector = AnomalyDetector(
            self._store, wc, baseline_hours=self._baseline_hours
        )

        count = await detector.detect_and_store(
            market_ids, self._window_configs, now_ms
        )

        self.logger.info(
            "detection_cycle_complete",
            markets_scanned=len(market_ids),
            anomalies_found=count,
        )
        return count

    async def run_forever(self) -> None:
        """Run detection cycles at the configured interval."""
        self._running = True
        while self._running:
            try:
                await self.run_once()
            except Exception:
                self.logger.exception("detection_cycle_error")
            await asyncio.sleep(self._interval)

    async def stop(self) -> None:
        """Stop the detection loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
