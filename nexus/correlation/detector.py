"""Anomaly detection engine for single-market anomalies."""

import time
from typing import List

from nexus.core.logging import LoggerMixin
from nexus.core.types import (
    AnomalyMarketRecord,
    AnomalyRecord,
    AnomalyType,
    WindowConfig,
)
from nexus.correlation.windows import WindowComputer
from nexus.store.base import BaseStore


class AnomalyDetector(LoggerMixin):
    """Detects single-market anomalies using windowed statistics."""

    def __init__(
        self,
        store: BaseStore,
        window_computer: WindowComputer,
        baseline_hours: int = 24,
    ) -> None:
        self._store = store
        self._wc = window_computer
        self._baseline_hours = baseline_hours

    async def detect_market(
        self,
        market_id: int,
        window_configs: List[WindowConfig],
        now_ms: int,
    ) -> List[AnomalyRecord]:
        """Run detection rules for a single market across all window configs."""
        anomalies: List[AnomalyRecord] = []

        for wc in window_configs:
            stats = await self._wc.compute_window(
                market_id, wc.window_minutes, now_ms
            )

            if stats.event_count == 0:
                continue

            # Rule 1: Price change threshold
            price_score = 0.0
            if stats.price_change_pct is not None:
                abs_change = abs(stats.price_change_pct)
                if abs_change > wc.price_change_threshold:
                    price_score = min(1.0, abs_change / wc.price_change_threshold)

            # Rule 2: Volume spike
            volume_score = 0.0
            if stats.volume_total > 0:
                baseline = await self._wc.compute_baseline(
                    market_id, "volume", self._baseline_hours,
                    wc.window_minutes, now_ms,
                )
                if baseline.mean > 0:
                    ratio = stats.volume_total / baseline.mean
                    if ratio > wc.volume_spike_multiplier:
                        volume_score = min(1.0, ratio / (wc.volume_spike_multiplier * 2))

            # Rule 3: Z-score on price change
            zscore_score = 0.0
            if stats.price_change_pct is not None:
                baseline = await self._wc.compute_baseline(
                    market_id, "price_change_pct", self._baseline_hours,
                    wc.window_minutes, now_ms,
                )
                if baseline.stddev > 0:
                    zscore = abs(stats.price_change_pct - baseline.mean) / baseline.stddev
                    if zscore > wc.zscore_threshold:
                        zscore_score = min(1.0, zscore / (wc.zscore_threshold * 2))

            severity = max(price_score, volume_score, zscore_score)

            if severity > 0:
                parts = []
                if price_score > 0 and stats.price_change_pct is not None:
                    parts.append(f"{stats.price_change_pct:+.1%} price")
                if volume_score > 0:
                    parts.append(f"{stats.volume_total:.0f} vol")
                if zscore_score > 0:
                    parts.append("z-score breach")
                trigger_desc = ", ".join(parts)
                summary = f"market_id={market_id}: {trigger_desc} in {wc.window_minutes}min window"

                anomaly = AnomalyRecord(
                    anomaly_type=AnomalyType.SINGLE_MARKET,
                    severity=round(severity, 4),
                    market_count=1,
                    window_start=stats.window_start,
                    detected_at=now_ms,
                    summary=summary,
                )
                anomalies.append(anomaly)

        return anomalies

    async def detect_all(
        self,
        market_ids: List[int],
        window_configs: List[WindowConfig],
        now_ms: int,
    ) -> List[AnomalyRecord]:
        """Run detection across all provided markets."""
        all_anomalies: List[AnomalyRecord] = []

        for mid in market_ids:
            market_anomalies = await self.detect_market(mid, window_configs, now_ms)
            all_anomalies.extend(market_anomalies)

        return all_anomalies

    async def detect_and_store(
        self,
        market_ids: List[int],
        window_configs: List[WindowConfig],
        now_ms: int,
    ) -> int:
        """Detect anomalies and store them. Returns count of anomalies stored."""
        anomalies = await self.detect_all(market_ids, window_configs, now_ms)

        for anomaly in anomalies:
            # Extract market_id from summary (it's always a single-market anomaly)
            # Parse from the anomaly we just created
            market_id = self._extract_market_id(anomaly.summary or "")
            links = []
            if market_id is not None:
                links = [AnomalyMarketRecord(
                    anomaly_id=0,  # Will be set by store
                    market_id=market_id,
                )]
            await self._store.insert_anomaly(anomaly, links)

        return len(anomalies)

    @staticmethod
    def _extract_market_id(summary: str) -> int | None:
        """Extract market_id from summary string like 'market_id=42: ...'."""
        if summary.startswith("market_id="):
            try:
                return int(summary.split("=")[1].split(":")[0])
            except (IndexError, ValueError):
                return None
        return None
