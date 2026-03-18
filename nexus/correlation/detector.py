"""Anomaly detection engine for single-market anomalies."""

import math
import re
import time
from typing import Dict, List, Optional

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
        self._title_cache: Dict[int, str] = {}

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
            # Use logarithmic scaling so 2x threshold ≈ 0.5, 10x ≈ 0.8, 100x ≈ 1.0
            price_score = 0.0
            if stats.price_change_pct is not None:
                abs_change = abs(stats.price_change_pct)
                if abs_change > wc.price_change_threshold:
                    ratio = abs_change / wc.price_change_threshold
                    price_score = min(1.0, math.log10(ratio + 1) / math.log10(101))

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
                # Look up market title for human-readable summary
                title = await self._get_market_title(market_id)

                parts = []
                if price_score > 0 and stats.price_change_pct is not None:
                    price_desc = f"{stats.price_change_pct:+.1%}"
                    if stats.price_start is not None and stats.price_end is not None:
                        price_desc += f" ({stats.price_start:.0%}→{stats.price_end:.0%})"
                    parts.append(price_desc)
                if volume_score > 0:
                    parts.append(f"{stats.volume_total:.0f} vol")
                if zscore_score > 0:
                    parts.append("z-score breach")
                trigger_desc = ", ".join(parts)
                summary = f"{title}: {trigger_desc} in {wc.window_minutes}min window"

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
        """Detect anomalies and store them. Returns count of anomalies stored.

        Deduplicates: only stores the highest-severity anomaly per market
        (across all windows) to avoid flooding with repeated alerts.
        """
        from nexus.core.types import AnomalyStatus

        # Check which markets already have active anomalies — skip those
        existing = await self._store.get_anomalies(
            status=AnomalyStatus.ACTIVE,
            anomaly_type="single_market",
        )
        existing_market_ids: set[int] = set()
        for a in existing:
            if a.id is not None:
                links = await self._store.get_anomaly_markets(a.id)
                for link in links:
                    existing_market_ids.add(link.market_id)

        count = 0
        for mid in market_ids:
            if mid in existing_market_ids:
                continue
            anomalies = await self.detect_market(mid, window_configs, now_ms)
            if not anomalies:
                continue
            # Only store the highest-severity anomaly per market
            anomaly = max(anomalies, key=lambda a: a.severity)
            anomalies = [anomaly]
            for anomaly in anomalies:
                # Compute price_delta and volume_ratio for market links
                wm = self._parse_window_minutes(anomaly.summary or "")
                price_delta = None
                volume_ratio = None
                if wm is not None:
                    stats = await self._wc.compute_window(mid, wm, now_ms)
                    price_delta = stats.price_delta
                    if stats.volume_total > 0:
                        baseline = await self._wc.compute_baseline(
                            mid, "volume", self._baseline_hours, wm, now_ms
                        )
                        if baseline.mean > 0:
                            volume_ratio = round(
                                stats.volume_total / baseline.mean, 2
                            )

                links = [AnomalyMarketRecord(
                    anomaly_id=0,
                    market_id=mid,
                    price_delta=price_delta,
                    volume_ratio=volume_ratio,
                )]
                await self._store.insert_anomaly(anomaly, links)
                count += 1

        return count

    async def _get_market_title(self, market_id: int) -> str:
        """Look up market title, with caching to avoid repeated DB hits."""
        if market_id in self._title_cache:
            return self._title_cache[market_id]
        market = await self._store.get_market_by_id(market_id)
        title = market.title if market else f"market_id={market_id}"
        # Truncate very long titles (some Kalshi combo markets)
        if len(title) > 80:
            title = title[:77] + "..."
        self._title_cache[market_id] = title
        return title

    @staticmethod
    def _parse_window_minutes(summary: str) -> Optional[int]:
        """Extract window minutes from summary like '... in 60min window'."""
        match = re.search(r"in (\d+)min window", summary)
        return int(match.group(1)) if match else None
