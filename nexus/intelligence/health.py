"""Market health score — synthesizes trade flow, orderbook, and momentum.

Each market gets a 0.0–1.0 health score composed of five signals:

- **Trade velocity** (0.25): trades per minute, normalized
- **Orderbook imbalance** (0.20): buy vs sell depth ratio
- **Whale activity** (0.20): % of volume from large trades (>$500)
- **Spread tightness** (0.15): 1 - spread/max_spread
- **Momentum** (0.20): directional consistency of recent price changes

All computation is in-memory with rolling windows — no database tables.
"""

from __future__ import annotations

import json
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Sequence

from nexus.adapters.base import BaseAdapter
from nexus.core.logging import LoggerMixin
from nexus.core.types import EventRecord, EventType

# ── Configuration ────────────────────────────────────────────────

# Health score weights (must sum to 1.0)
W_TRADE_VELOCITY = 0.25
W_ORDERBOOK_IMBALANCE = 0.20
W_WHALE_ACTIVITY = 0.20
W_SPREAD_TIGHTNESS = 0.15
W_MOMENTUM = 0.20

# Rolling window sizes
TRADE_WINDOW_SECONDS = 900  # 15 minutes of trades
PRICE_WINDOW_SECONDS = 3600  # 1 hour of price ticks
MAX_TRADES_PER_MARKET = 500  # Cap to prevent memory bloat

# Normalization thresholds
MAX_TRADES_PER_MIN = 10.0  # 10 trades/min = velocity score 1.0
WHALE_THRESHOLD = 500.0  # Trades > $500 count as whale activity
MAX_SPREAD = 0.10  # 10c spread = spread score 0.0


# ── Data structures ──────────────────────────────────────────────


@dataclass
class TradeRecord:
    """A single trade for rolling window analysis."""

    timestamp: float  # Unix seconds
    price: float  # YES price (0-1)
    size: float  # Contract count (from count_fp)
    taker_side: str  # "yes" or "no"
    dollar_value: float  # price * size (approximate notional)


@dataclass
class OrderbookSnapshot:
    """Point-in-time orderbook summary."""

    timestamp: float
    bid_depth: float  # Total contracts on bid side
    ask_depth: float  # Total contracts on ask side
    best_bid: float  # Best bid price
    best_ask: float  # Best ask price
    spread: float  # best_ask - best_bid
    levels: int  # Number of price levels


@dataclass
class HealthComponents:
    """Breakdown of the health score into its components."""

    trade_velocity: float = 0.0
    orderbook_imbalance: float = 0.0
    whale_activity: float = 0.0
    spread_tightness: float = 0.0
    momentum: float = 0.0
    health_score: float = 0.0
    trade_count: int = 0
    has_orderbook: bool = False


@dataclass
class MarketState:
    """Rolling state for a single market."""

    trades: Deque[TradeRecord] = field(default_factory=lambda: deque(maxlen=MAX_TRADES_PER_MARKET))
    prices: Deque[tuple[float, float]] = field(
        default_factory=lambda: deque(maxlen=200)
    )  # (timestamp, price)
    orderbook: Optional[OrderbookSnapshot] = None
    last_health: Optional[HealthComponents] = None


# ── Main tracker ─────────────────────────────────────────────────


class MarketHealthTracker(LoggerMixin):
    """In-memory tracker that computes health scores from trade flow and orderbook data.

    Usage::

        tracker = MarketHealthTracker()
        tracker.process_event(event)          # Feed TRADE/PRICE_CHANGE events
        tracker.update_orderbook("TICK", ob)  # Feed orderbook snapshots
        scores = tracker.get_health_scores()  # {external_id: 0.0-1.0}
    """

    def __init__(self, max_markets: int = 500) -> None:
        self._markets: Dict[str, MarketState] = {}
        self._max_markets = max_markets

    # ------------------------------------------------------------------
    # Event ingestion
    # ------------------------------------------------------------------

    def process_event(self, event: EventRecord) -> None:
        """Process a resolved event and update the rolling state.

        Call this from the IngestionManager after ticker resolution.
        Handles TRADE and PRICE_CHANGE events.
        """
        if event.event_type == EventType.TRADE:
            self._process_trade(event)
        elif event.event_type == EventType.PRICE_CHANGE:
            self._process_price(event)

    def _process_trade(self, event: EventRecord) -> None:
        """Extract trade details from metadata and add to rolling window."""
        meta = self._parse_metadata(event.metadata)
        if not meta:
            return

        ticker = meta.get("ticker", "")
        if not ticker:
            return

        state = self._get_or_create(ticker)

        # Parse trade fields
        count_str = meta.get("count") or "1"
        try:
            count = float(count_str)
        except (ValueError, TypeError):
            count = 1.0

        price = event.new_value
        taker_side = meta.get("taker_side", "unknown")
        dollar_value = price * count

        trade = TradeRecord(
            timestamp=event.timestamp / 1000.0,
            price=price,
            size=count,
            taker_side=taker_side,
            dollar_value=dollar_value,
        )
        state.trades.append(trade)

        # Also record as a price point
        state.prices.append((trade.timestamp, price))

    def _process_price(self, event: EventRecord) -> None:
        """Record a price tick for momentum analysis."""
        meta = self._parse_metadata(event.metadata)
        if not meta:
            return

        ticker = meta.get("ticker", "")
        if not ticker:
            return

        state = self._get_or_create(ticker)
        state.prices.append((event.timestamp / 1000.0, event.new_value))

    # ------------------------------------------------------------------
    # Orderbook ingestion
    # ------------------------------------------------------------------

    def update_orderbook(self, ticker: str, orderbook: OrderbookSnapshot) -> None:
        """Store an orderbook snapshot for a market."""
        state = self._get_or_create(ticker)
        state.orderbook = orderbook

    @staticmethod
    def parse_orderbook_response(
        data: Dict[str, Any],
    ) -> Optional[OrderbookSnapshot]:
        """Parse a Kalshi GET /markets/{ticker}/orderbook response.

        Expected structure::

            {
                "orderbook": {
                    "yes": [[price, size], ...],
                    "no":  [[price, size], ...]
                }
            }
        """
        ob = data.get("orderbook", {})
        yes_levels = ob.get("yes") or []
        no_levels = ob.get("no") or []

        if not yes_levels and not no_levels:
            return None

        bid_depth = 0.0
        ask_depth = 0.0
        best_bid = 0.0
        best_ask = 1.0

        for level in yes_levels:
            if len(level) >= 2:
                price = float(level[0])
                size = float(level[1])
                bid_depth += size
                best_bid = max(best_bid, price)

        for level in no_levels:
            if len(level) >= 2:
                price = float(level[0])
                size = float(level[1])
                # NO side ask = 1 - no_price
                ask_price = 1.0 - price
                ask_depth += size
                best_ask = min(best_ask, ask_price)

        # If we only have YES levels, estimate ask from best bid + spread
        if yes_levels and not no_levels:
            best_ask = min(1.0, best_bid + 0.02)  # Assume 2c spread
        if no_levels and not yes_levels:
            best_bid = max(0.0, best_ask - 0.02)

        spread = max(0.0, best_ask - best_bid)

        return OrderbookSnapshot(
            timestamp=time.time(),
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            levels=len(yes_levels) + len(no_levels),
        )

    # ------------------------------------------------------------------
    # Health score computation
    # ------------------------------------------------------------------

    def compute_health(self, ticker: str) -> HealthComponents:
        """Compute the health score breakdown for a single market."""
        state = self._markets.get(ticker)
        if state is None:
            return HealthComponents()

        now = time.time()
        components = HealthComponents()

        # 1. Trade velocity
        components.trade_velocity = self._compute_trade_velocity(state, now)

        # 2. Orderbook imbalance
        components.orderbook_imbalance = self._compute_orderbook_imbalance(state)
        components.has_orderbook = state.orderbook is not None

        # 3. Whale activity
        components.whale_activity = self._compute_whale_activity(state, now)

        # 4. Spread tightness
        components.spread_tightness = self._compute_spread_tightness(state)

        # 5. Momentum
        components.momentum = self._compute_momentum(state, now)

        # Count recent trades
        cutoff = now - TRADE_WINDOW_SECONDS
        components.trade_count = sum(
            1 for t in state.trades if t.timestamp >= cutoff
        )

        # Weighted sum
        components.health_score = (
            W_TRADE_VELOCITY * components.trade_velocity
            + W_ORDERBOOK_IMBALANCE * components.orderbook_imbalance
            + W_WHALE_ACTIVITY * components.whale_activity
            + W_SPREAD_TIGHTNESS * components.spread_tightness
            + W_MOMENTUM * components.momentum
        )

        state.last_health = components
        return components

    def get_health_scores(self) -> Dict[str, float]:
        """Compute and return health scores for all tracked markets.

        Returns a dict of ``{ticker: score}`` where score is 0.0–1.0.
        """
        scores: Dict[str, float] = {}
        for ticker in list(self._markets.keys()):
            components = self.compute_health(ticker)
            if components.trade_count > 0 or components.has_orderbook:
                scores[ticker] = components.health_score
        return scores

    def get_health_details(self) -> Dict[str, HealthComponents]:
        """Return detailed health breakdowns for all markets with activity."""
        details: Dict[str, HealthComponents] = {}
        for ticker in list(self._markets.keys()):
            components = self.compute_health(ticker)
            if components.trade_count > 0 or components.has_orderbook:
                details[ticker] = components
        return details

    # ------------------------------------------------------------------
    # Individual signal computations
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_trade_velocity(state: MarketState, now: float) -> float:
        """Trades per minute, normalized to [0, 1]."""
        cutoff = now - TRADE_WINDOW_SECONDS
        recent = [t for t in state.trades if t.timestamp >= cutoff]
        if not recent:
            return 0.0

        window_minutes = TRADE_WINDOW_SECONDS / 60.0
        velocity = len(recent) / window_minutes
        return min(1.0, velocity / MAX_TRADES_PER_MIN)

    @staticmethod
    def _compute_orderbook_imbalance(state: MarketState) -> float:
        """Buy/sell depth imbalance, normalized to [0, 1].

        0.0 = perfectly balanced, 1.0 = completely one-sided.
        """
        ob = state.orderbook
        if ob is None or (ob.bid_depth + ob.ask_depth) == 0:
            return 0.0

        imbalance = abs(ob.bid_depth - ob.ask_depth) / (ob.bid_depth + ob.ask_depth)
        return min(1.0, imbalance)

    @staticmethod
    def _compute_whale_activity(state: MarketState, now: float) -> float:
        """Fraction of recent volume from large trades (>$500)."""
        cutoff = now - TRADE_WINDOW_SECONDS
        recent = [t for t in state.trades if t.timestamp >= cutoff]
        if not recent:
            return 0.0

        total_volume = sum(t.dollar_value for t in recent)
        if total_volume == 0:
            return 0.0

        whale_volume = sum(
            t.dollar_value for t in recent if t.dollar_value >= WHALE_THRESHOLD
        )
        return min(1.0, whale_volume / total_volume)

    @staticmethod
    def _compute_spread_tightness(state: MarketState) -> float:
        """How tight the bid-ask spread is, normalized to [0, 1].

        1.0 = zero spread (max liquidity), 0.0 = MAX_SPREAD or wider.
        """
        ob = state.orderbook
        if ob is None:
            # No orderbook data — estimate from recent trade prices
            return 0.5  # Neutral default

        tightness = 1.0 - (ob.spread / MAX_SPREAD)
        return max(0.0, min(1.0, tightness))

    @staticmethod
    def _compute_momentum(state: MarketState, now: float) -> float:
        """Directional consistency of recent price changes.

        1.0 = all moves in one direction (strong trend),
        0.0 = no movement or perfectly oscillating.
        """
        cutoff = now - PRICE_WINDOW_SECONDS
        recent_prices = [(ts, p) for ts, p in state.prices if ts >= cutoff]
        if len(recent_prices) < 3:
            return 0.0

        # Count consecutive same-direction moves
        ups = 0
        downs = 0
        for i in range(1, len(recent_prices)):
            delta = recent_prices[i][1] - recent_prices[i - 1][1]
            if delta > 0:
                ups += 1
            elif delta < 0:
                downs += 1

        total_moves = ups + downs
        if total_moves == 0:
            return 0.0

        # Momentum = how one-sided the moves are
        dominant = max(ups, downs)
        consistency = dominant / total_moves

        # Scale: 50% same direction = 0.0, 100% = 1.0
        momentum = max(0.0, (consistency - 0.5) * 2.0)

        # Also factor in magnitude
        first_price = recent_prices[0][1]
        last_price = recent_prices[-1][1]
        if first_price > 0:
            abs_change = abs(last_price - first_price) / first_price
            # Scale up momentum if the move is large
            magnitude_boost = min(1.0, abs_change / 0.05)  # 5% move = max boost
            momentum = min(1.0, momentum * (0.5 + 0.5 * magnitude_boost))

        return momentum

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def prune_stale(self, max_age_seconds: float = 3600.0) -> int:
        """Remove markets with no recent activity to limit memory."""
        now = time.time()
        stale = []
        for ticker, state in self._markets.items():
            latest_trade = state.trades[-1].timestamp if state.trades else 0
            latest_price = state.prices[-1][0] if state.prices else 0
            latest = max(latest_trade, latest_price)
            if now - latest > max_age_seconds:
                stale.append(ticker)

        for ticker in stale:
            del self._markets[ticker]
        return len(stale)

    @property
    def tracked_count(self) -> int:
        """Number of markets currently being tracked."""
        return len(self._markets)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_create(self, ticker: str) -> MarketState:
        """Get or create market state, evicting oldest if at capacity."""
        if ticker in self._markets:
            return self._markets[ticker]

        # Evict oldest market if at capacity
        if len(self._markets) >= self._max_markets:
            self.prune_stale(max_age_seconds=1800)
            # If still at capacity, remove the oldest
            if len(self._markets) >= self._max_markets:
                oldest_ticker = next(iter(self._markets))
                del self._markets[oldest_ticker]

        self._markets[ticker] = MarketState()
        return self._markets[ticker]

    @staticmethod
    def _parse_metadata(metadata: Optional[str]) -> Optional[Dict[str, Any]]:
        """Parse JSON metadata string, returning None on failure."""
        if not metadata:
            return None
        try:
            return json.loads(metadata)
        except (json.JSONDecodeError, TypeError):
            return None
