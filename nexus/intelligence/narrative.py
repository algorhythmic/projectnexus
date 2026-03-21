"""Catalyst attribution — structured analysis for anomaly context.

When an anomaly fires, this module gathers contextual signals to help
explain *why* the market moved.  The output is a structured dict that
can be:
  1. Stored as-is in anomaly metadata (Sprint 4)
  2. Fed to an LLM for narrative generation (Phase 5)

Signals gathered:
  - Trade flow pattern (velocity, whale %, taker imbalance)
  - Time clustering (was the move concentrated in a burst?)
  - Price magnitude and direction
  - Market context (category, series, expiry proximity)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from nexus.core.logging import LoggerMixin
from nexus.core.types import AnomalyRecord, EventRecord, MarketRecord


@dataclass
class CatalystAnalysis:
    """Structured analysis of what likely drove a price movement."""

    # Price movement
    direction: str  # "up", "down", "mixed"
    magnitude_pct: float  # Absolute price change
    price_from: Optional[float] = None
    price_to: Optional[float] = None

    # Trade flow
    trade_count: int = 0
    trades_per_minute: float = 0.0
    whale_trade_pct: float = 0.0  # % of volume from large trades
    taker_buy_pct: float = 0.0  # % of volume on the buy (yes) side
    avg_trade_size: float = 0.0

    # Time clustering
    burst_detected: bool = False
    burst_duration_seconds: float = 0.0
    burst_trade_pct: float = 0.0  # % of trades in the burst window

    # Market context
    category: str = ""
    series_prefix: str = ""
    hours_to_expiry: Optional[float] = None
    markets_in_series: int = 0

    # Attribution confidence (0-1)
    confidence: float = 0.0

    # Suggested catalyst type
    catalyst_type: str = "unknown"  # "news", "data_release", "whale", "momentum", "pre_resolution"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class CatalystAnalyzer(LoggerMixin):
    """Gathers contextual signals to explain anomalous price movements.

    Usage::

        analyzer = CatalystAnalyzer()
        analysis = analyzer.analyze_events(events, market)
        # Store analysis.to_json() in anomaly metadata
    """

    # A "burst" is when >60% of trades happen in <20% of the window
    BURST_TRADE_PCT_THRESHOLD = 0.60
    BURST_WINDOW_FRACTION = 0.20

    # Whale trade threshold ($)
    WHALE_DOLLAR_THRESHOLD = 500.0

    def analyze_events(
        self,
        events: List[EventRecord],
        market: Optional[MarketRecord] = None,
        window_minutes: int = 15,
    ) -> CatalystAnalysis:
        """Analyze a set of events to attribute the likely catalyst.

        Args:
            events: Events in the anomaly window (price_change + trade).
            market: Market metadata for context.
            window_minutes: The detection window size.

        Returns:
            Structured catalyst analysis.
        """
        analysis = CatalystAnalysis(direction="unknown", magnitude_pct=0.0)

        # Split by type
        price_events = [e for e in events if e.event_type.value == "price_change"]
        trade_events = [e for e in events if e.event_type.value == "trade"]

        # Price movement
        if price_events:
            self._analyze_price(analysis, price_events)

        # Trade flow
        if trade_events:
            self._analyze_trades(analysis, trade_events, window_minutes)
            self._detect_burst(analysis, trade_events, window_minutes)

        # Market context
        if market:
            self._add_market_context(analysis, market)

        # Infer catalyst type
        self._infer_catalyst_type(analysis)

        return analysis

    def _analyze_price(
        self, analysis: CatalystAnalysis, events: List[EventRecord]
    ) -> None:
        """Compute price direction and magnitude."""
        sorted_events = sorted(events, key=lambda e: e.timestamp)
        first = sorted_events[0].new_value
        last = sorted_events[-1].new_value

        analysis.price_from = first
        analysis.price_to = last

        if first > 0:
            change = (last - first) / first
            analysis.magnitude_pct = abs(change)
            analysis.direction = "up" if change > 0 else "down" if change < 0 else "flat"
        else:
            analysis.direction = "unknown"

    def _analyze_trades(
        self,
        analysis: CatalystAnalysis,
        events: List[EventRecord],
        window_minutes: int,
    ) -> None:
        """Compute trade flow metrics."""
        analysis.trade_count = len(events)
        analysis.trades_per_minute = len(events) / max(window_minutes, 1)

        total_volume = 0.0
        whale_volume = 0.0
        buy_volume = 0.0
        total_size = 0.0

        for e in events:
            meta = self._parse_meta(e.metadata)
            count = self._parse_float(meta.get("count"), 1.0)
            dollar_value = e.new_value * count
            total_volume += dollar_value
            total_size += count

            if dollar_value >= self.WHALE_DOLLAR_THRESHOLD:
                whale_volume += dollar_value

            taker = meta.get("taker_side", "")
            if taker == "yes":
                buy_volume += dollar_value

        if total_volume > 0:
            analysis.whale_trade_pct = whale_volume / total_volume
            analysis.taker_buy_pct = buy_volume / total_volume

        if len(events) > 0:
            analysis.avg_trade_size = total_size / len(events)

    def _detect_burst(
        self,
        analysis: CatalystAnalysis,
        events: List[EventRecord],
        window_minutes: int,
    ) -> None:
        """Detect if trades are concentrated in a short burst."""
        if len(events) < 5:
            return

        sorted_events = sorted(events, key=lambda e: e.timestamp)
        window_ms = window_minutes * 60 * 1000
        burst_window_ms = int(window_ms * self.BURST_WINDOW_FRACTION)

        # Sliding window: find the burst_window_ms interval with the most trades
        max_count = 0
        max_start = 0

        for i, e in enumerate(sorted_events):
            start_ts = e.timestamp
            end_ts = start_ts + burst_window_ms
            count = sum(1 for ev in sorted_events[i:] if ev.timestamp <= end_ts)
            if count > max_count:
                max_count = count
                max_start = start_ts

        burst_pct = max_count / len(events)
        if burst_pct >= self.BURST_TRADE_PCT_THRESHOLD:
            analysis.burst_detected = True
            analysis.burst_trade_pct = burst_pct
            # Find actual burst duration (first to last trade in the burst)
            burst_trades = [
                e for e in sorted_events
                if max_start <= e.timestamp <= max_start + burst_window_ms
            ]
            if len(burst_trades) >= 2:
                analysis.burst_duration_seconds = (
                    burst_trades[-1].timestamp - burst_trades[0].timestamp
                ) / 1000.0

    def _add_market_context(
        self, analysis: CatalystAnalysis, market: MarketRecord
    ) -> None:
        """Add market metadata context."""
        analysis.category = market.category or ""

        # Series prefix
        parts = market.external_id.split("-")
        if len(parts) >= 2:
            analysis.series_prefix = parts[0]

        # Hours to expiry
        if hasattr(market, "end_date") and market.description:
            # end_date might be in the market or description
            pass  # Will be enriched when end_date is available as datetime

    def _infer_catalyst_type(self, analysis: CatalystAnalysis) -> None:
        """Infer the most likely catalyst type from signals."""
        confidence = 0.0

        # Whale-driven: high whale %, moderate trade count
        if analysis.whale_trade_pct >= 0.5 and analysis.trade_count >= 3:
            analysis.catalyst_type = "whale"
            confidence = 0.3 + 0.4 * analysis.whale_trade_pct

        # News/data burst: concentrated trades in short window
        elif analysis.burst_detected and analysis.burst_trade_pct >= 0.7:
            analysis.catalyst_type = "news"
            confidence = 0.4 + 0.3 * analysis.burst_trade_pct

        # Momentum: consistent direction, many trades, no whale dominance
        elif (
            analysis.trade_count >= 10
            and analysis.whale_trade_pct < 0.3
            and analysis.magnitude_pct >= 0.05
        ):
            analysis.catalyst_type = "momentum"
            confidence = 0.3 + 0.3 * min(1.0, analysis.trades_per_minute / 5.0)

        # Pre-resolution: near expiry with strong directional move
        elif (
            analysis.hours_to_expiry is not None
            and analysis.hours_to_expiry < 4
            and analysis.magnitude_pct >= 0.1
        ):
            analysis.catalyst_type = "pre_resolution"
            confidence = 0.5

        else:
            analysis.catalyst_type = "unknown"
            confidence = 0.1

        analysis.confidence = min(1.0, confidence)

    @staticmethod
    def _parse_meta(metadata: Optional[str]) -> Dict[str, Any]:
        if not metadata:
            return {}
        try:
            return json.loads(metadata)
        except (json.JSONDecodeError, TypeError):
            return {}

    @staticmethod
    def _parse_float(value: Any, default: float = 0.0) -> float:
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
