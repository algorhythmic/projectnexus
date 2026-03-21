"""Series pattern detector — detects synchronized movements across related markets.

Kalshi markets are organized in series (e.g., daily BTC price markets,
weekly weather markets).  When multiple markets in a series move in the
same direction within a short window, it's a strong signal — often driven
by a common catalyst (news event, data release, resolution approaching).

This detector runs after single-market anomaly detection in the
DetectionLoop and produces ``AnomalyType.CLUSTER`` anomalies with
``source: series_pattern`` metadata.
"""

from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from nexus.core.logging import LoggerMixin
from nexus.core.types import (
    AnomalyMarketRecord,
    AnomalyRecord,
    AnomalyStatus,
    AnomalyType,
    EventRecord,
)
from nexus.store.base import BaseStore

# Minimum markets in a series that must move together
DEFAULT_MIN_MOVERS = 3
# Time window to check for coordinated moves (minutes)
DEFAULT_WINDOW_MINUTES = 30
# Minimum absolute price change to count as "moving"
DEFAULT_PRICE_THRESHOLD = 0.03  # 3%


class SeriesPatternDetector(LoggerMixin):
    """Detects synchronized price movements within market series.

    A "series" is a group of markets sharing the same ticker prefix
    (e.g., all ``INXD-*`` markets belong to the S&P 500 series).

    Detection algorithm:
        1. Group recently-active markets by series prefix.
        2. For each series with enough markets, compute price change
           over the window for each market.
        3. If N+ markets moved in the same direction, emit a series
           pattern anomaly with severity based on the magnitude and
           breadth of the move.
    """

    def __init__(
        self,
        store: BaseStore,
        min_movers: int = DEFAULT_MIN_MOVERS,
        window_minutes: int = DEFAULT_WINDOW_MINUTES,
        price_threshold: float = DEFAULT_PRICE_THRESHOLD,
    ) -> None:
        self._store = store
        self._min_movers = min_movers
        self._window_minutes = window_minutes
        self._price_threshold = price_threshold

    async def detect_and_store(
        self,
        market_ids: List[int],
        now_ms: int,
    ) -> int:
        """Run series pattern detection across the given markets.

        Args:
            market_ids: Markets that had recent activity.
            now_ms: Current timestamp (Unix ms).

        Returns:
            Number of series anomalies created.
        """
        # Group markets by series prefix
        series_groups = await self._group_by_series(market_ids)

        count = 0
        for series_prefix, markets in series_groups.items():
            if len(markets) < self._min_movers:
                continue

            anomaly = await self._analyze_series(
                series_prefix, markets, now_ms
            )
            if anomaly is not None:
                count += 1

        if count > 0:
            self.logger.info(
                "series_patterns_detected",
                count=count,
                series_checked=len(series_groups),
            )
        return count

    async def _group_by_series(
        self, market_ids: List[int]
    ) -> Dict[str, List[Tuple[int, str]]]:
        """Group market IDs by their series prefix.

        Returns {series_prefix: [(market_id, external_id), ...]}.
        """
        groups: Dict[str, List[Tuple[int, str]]] = defaultdict(list)

        for mid in market_ids:
            market = await self._store.get_market_by_id(mid)
            if market is None or not market.is_active:
                continue
            prefix = self._extract_series_prefix(market.external_id)
            if prefix:
                groups[prefix].append((mid, market.external_id))

        return groups

    @staticmethod
    def _extract_series_prefix(external_id: str) -> Optional[str]:
        """Extract the series prefix from a market ticker.

        Returns the first hyphen-separated segment, or None if the
        ticker has no hyphens (single-segment = standalone market).
        """
        parts = external_id.split("-")
        if len(parts) >= 2:
            return parts[0]
        return None

    async def _analyze_series(
        self,
        series_prefix: str,
        markets: List[Tuple[int, str]],
        now_ms: int,
    ) -> Optional[int]:
        """Check if markets in a series are moving together.

        Returns the anomaly ID if a pattern is detected, None otherwise.
        """
        window_start = now_ms - (self._window_minutes * 60 * 1000)

        # Compute price change for each market in the window
        movers_up: List[Tuple[int, str, float]] = []  # (id, ticker, change)
        movers_down: List[Tuple[int, str, float]] = []

        for mid, ticker in markets:
            events = await self._store.get_events_in_window(
                mid, "price_change", window_start, now_ms
            )
            if len(events) < 2:
                continue

            first_price = events[0].new_value
            last_price = events[-1].new_value
            if first_price == 0:
                continue

            change_pct = (last_price - first_price) / first_price

            if change_pct >= self._price_threshold:
                movers_up.append((mid, ticker, change_pct))
            elif change_pct <= -self._price_threshold:
                movers_down.append((mid, ticker, change_pct))

        # Check if enough markets moved in the same direction
        dominant_movers = movers_up if len(movers_up) >= len(movers_down) else movers_down
        direction = "up" if dominant_movers is movers_up else "down"

        if len(dominant_movers) < self._min_movers:
            return None

        # Check for existing active anomaly for this series to avoid duplicates
        existing = await self._store.get_anomalies(
            since=window_start,
            anomaly_type="cluster",
            limit=100,
        )
        for a in existing:
            if a.metadata:
                try:
                    meta = json.loads(a.metadata)
                    if (
                        meta.get("source") == "series_pattern"
                        and meta.get("series_prefix") == series_prefix
                    ):
                        return None  # Already detected
                except (json.JSONDecodeError, TypeError):
                    pass

        # Compute severity: breadth × magnitude
        breadth = len(dominant_movers) / len(markets)  # What fraction moved
        avg_magnitude = sum(abs(c) for _, _, c in dominant_movers) / len(dominant_movers)
        # Log-scaled severity: breadth (50%) + magnitude (50%)
        severity = min(
            1.0,
            0.5 * breadth + 0.5 * min(1.0, math.log1p(avg_magnitude * 100) / 4),
        )

        summary = (
            f"Series {series_prefix}: {len(dominant_movers)}/{len(markets)} "
            f"markets moved {direction} by avg {avg_magnitude:.1%} "
            f"in {self._window_minutes}min"
        )

        metadata = json.dumps({
            "source": "series_pattern",
            "series_prefix": series_prefix,
            "direction": direction,
            "movers": len(dominant_movers),
            "total_markets": len(markets),
            "avg_change_pct": round(avg_magnitude, 4),
            "tickers": [t for _, t, _ in dominant_movers[:10]],
        })

        anomaly = AnomalyRecord(
            anomaly_type=AnomalyType.CLUSTER,
            severity=severity,
            market_count=len(dominant_movers),
            window_start=window_start,
            detected_at=now_ms,
            summary=summary,
            status=AnomalyStatus.ACTIVE,
            metadata=metadata,
        )

        market_links = [
            AnomalyMarketRecord(
                anomaly_id=0,  # Filled by store
                market_id=mid,
                price_delta=change,
            )
            for mid, _, change in dominant_movers
        ]

        anomaly_id = await self._store.insert_anomaly(anomaly, market_links)
        self.logger.info(
            "series_pattern_anomaly",
            series=series_prefix,
            direction=direction,
            movers=len(dominant_movers),
            severity=f"{severity:.2f}",
            anomaly_id=anomaly_id,
        )
        return anomaly_id
