"""Kalshi prediction market adapter.

Implements the BaseAdapter interface for the Kalshi exchange.
Phase 1 (Milestone 1.1): REST-based market discovery with RSA-PSS auth.
Phase 1 (Milestone 1.2): WebSocket streaming (connect method).
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Set

import websockets
import websockets.exceptions

from nexus.adapters.auth import (
    RSAPrivateKey,
    generate_auth_headers,
    load_private_key,
    sign_request,
)
from nexus.adapters.base import BaseAdapter
from nexus.core.config import Settings
from nexus.core.types import DiscoveredMarket, EventRecord, EventType, Platform

# Mapping of Kalshi event categories (and legacy market categories)
# to standardized display names.  Keys are lowercased for case-insensitive lookup.
_CATEGORY_MAP: Dict[str, str] = {
    "economics": "Economics",
    "politics": "Politics",
    "elections": "Politics",
    "weather": "Weather",
    "climate": "Weather",
    "climate and weather": "Weather",
    "sports": "Sports",
    "entertainment": "Entertainment",
    "entertainment - movies": "Entertainment",
    "entertainment - music": "Entertainment",
    "entertainment - tv": "Entertainment",
    "culture": "Culture",
    "technology": "Technology",
    "tech": "Technology",
    "science": "Science",
    "science and technology": "Science",
    "science & technology": "Science",
    "health": "Science",
    "business": "Business",
    "financial": "Economics",
    "finance": "Economics",
    "crypto": "Cryptocurrency",
    "cryptocurrency": "Cryptocurrency",
    "mentions": "Social Media",
    "news": "News",
}


def _categorize_from_title(title: str) -> str:
    """Categorize a market based on title keywords."""
    t = title.lower()
    if any(w in t for w in ("election", "president", "congress", "senate", "vote", "poll",
                             "trump", "biden", "governor", "mayor", "democrat", "republican",
                             "pope", "cardinal", "conclave", "vatican", "papacy")):
        return "Politics"
    if any(w in t for w in ("bitcoin", "crypto", "ethereum", "btc", "eth", "solana")):
        return "Cryptocurrency"
    if any(w in t for w in ("gdp", "inflation", "fed", "economy", "unemployment", "interest rate",
                             "cpi", "jobs report", "payroll", "treasury")):
        return "Economics"
    if any(w in t for w in ("nfl", "nba", "mlb", "nhl", "super bowl", "world cup",
                             "wins by", "points scored", "championship", "playoff",
                             "arsenal", "liverpool", "lakers", "celtics", "march madness",
                             "ncaa", "pga", "ufc", "boxing", "tennis", "soccer",
                             "assists", "rebounds", "touchdowns", "goals",
                             "over ", "under ", "spread", "moneyline")):
        return "Sports"
    if any(w in t for w in ("temperature", "weather", "hurricane", "rain", "tornado",
                             "snowfall", "climate")):
        return "Weather"
    if any(w in t for w in ("movie", "film", "oscar", "emmy", "celebrity", "grammy", "netflix",
                             "actor", "actress", "bond", "hollywood", "box office", "disney",
                             "marvel", "tv show", "streaming", "perform", "role")):
        return "Entertainment"
    if any(w in t for w in ("fda", "drug", "vaccine", "cure", "diabetes", "cancer",
                             "disease", "pandemic", "virus", "clinical trial",
                             "medical", "pharmaceutical", "treatment", "health",
                             "ai ", "artificial intelligence", "space", "nasa", "launch",
                             "quantum", "fusion", "nuclear", "erupt", "volcano",
                             "earthquake", "asteroid", "extinction")):
        return "Science"
    if any(w in t for w in ("stock", "company", "ipo", "earnings", "s&p", "nasdaq", "dow")):
        return "Business"
    return "Other"


def _standardize_category(raw: Optional[str], title: str) -> str:
    """Use the Kalshi category verbatim if available, otherwise fall back
    to title-based heuristic."""
    if raw and raw.strip():
        # Title-case the raw category for consistent display
        return raw.strip().title()
    return _categorize_from_title(title)


def _calculate_yes_price(market: Dict[str, Any]) -> Optional[float]:
    """Extract the yes price from a Kalshi market object.

    Tries dollar-denominated fields (current API as of Jan 2026),
    then falls back to legacy cent fields for backward compat.
    Skips zero values (no orders / no trades).
    """
    for field in (
        "yes_ask_dollars",
        "yes_bid_dollars",
        "last_price_dollars",
        "yes_ask",
        "yes_bid",
        "last_price",
    ):
        val = market.get(field)
        if val is None:
            continue
        price = float(val)
        if price <= 0:
            continue
        # Legacy cents (0-100) → normalize to 0-1
        if price > 1.0:
            price /= 100.0
        return max(0.0, min(1.0, price))
    return None


class KalshiAdapter(BaseAdapter):
    """Adapter for the Kalshi prediction market exchange.

    Uses RSA-PSS signed authentication on every request.  Pagination
    is cursor-based (the ``cursor`` field in the response).
    """

    def __init__(self, settings: Settings) -> None:
        base_url = settings.effective_kalshi_url
        super().__init__(
            base_url=base_url,
            rate_limit=settings.kalshi_reads_per_second,
            timeout=settings.request_timeout,
        )
        self._settings = settings
        self._api_key = settings.kalshi_api_key
        self._private_key: Optional[RSAPrivateKey] = None
        self._key_path = settings.kalshi_private_key_path
        self._key_pem = settings.kalshi_private_key_pem

        # Extract URL path prefix for auth signing (e.g. "/trade-api/v2")
        from urllib.parse import urlparse
        self._url_path_prefix = urlparse(base_url).path.rstrip("/")

        # Load key from PEM string (containerized) or file path
        key_source = None
        if self._key_pem:
            key_source = self._key_pem.encode("utf-8")
        elif self._key_path:
            key_source = self._key_path

        if key_source:
            try:
                self._private_key = load_private_key(key_source)
                self.logger.info("Kalshi RSA private key loaded")
            except Exception as exc:
                self.logger.warning(
                    "Could not load Kalshi private key — "
                    "requests will be unauthenticated",
                    error=str(exc),
                )

        # Cache: event_ticker → data (persists across discovery cycles)
        self._event_category_cache: Dict[str, str] = {}
        self._event_title_cache: Dict[str, str] = {}

        # WebSocket state for dynamic subscription management (Feature D)
        self._ws: Optional[Any] = None  # Active WebSocket connection
        self._subscription_ids: List[int] = []  # SIDs from subscription confirmations
        self._ws_msg_counter: int = 0  # Incrementing message ID counter
        self._subscribed_tickers: Set[str] = set()  # Tickers currently subscribed

    # ------------------------------------------------------------------
    # Auth header override
    # ------------------------------------------------------------------

    def _build_headers(self, method: str, path: str) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._private_key and self._api_key:
            # Kalshi signs the full path (e.g. /trade-api/v2/markets)
            sign_path = f"{self._url_path_prefix}{path}"
            auth = generate_auth_headers(
                api_key=self._api_key,
                private_key=self._private_key,
                method=method,
                path=sign_path,
            )
            headers.update(auth)
        return headers

    # ------------------------------------------------------------------
    # discover()
    # ------------------------------------------------------------------

    async def discover(self) -> List[DiscoveredMarket]:
        """Enumerate active markets via cursor-paginated REST calls.

        Uses Kalshi API filters to reduce result volume:
        - status=open: only tradeable markets
        - mve_filter=exclude: skip multivariate combo markets (they have
          very long titles like "yes A,yes B,yes C" and rarely trade)
        """
        all_markets: List[DiscoveredMarket] = []
        # Map external_id → event_ticker for category enrichment
        raw_event_tickers: Dict[str, str] = {}
        cursor: Optional[str] = None
        max_pages = self._settings.kalshi_discovery_max_pages
        page = 0

        while True:
            params: Dict[str, Any] = {
                "limit": 200,
                "status": "open",
                "mve_filter": "exclude",
            }
            if cursor:
                params["cursor"] = cursor

            data = await self.make_request("GET", "markets", params=params)

            raw_markets = data.get("markets", [])
            if not raw_markets:
                break
            page += 1

            for raw in raw_markets:
                market = self._normalize(raw)
                if market is not None:
                    all_markets.append(market)
                    et = raw.get("event_ticker")
                    if et:
                        raw_event_tickers[market.external_id] = et

            cursor = data.get("cursor")
            if not cursor:
                break
            if max_pages and page >= max_pages:
                self.logger.info(
                    "Kalshi discovery page limit reached",
                    pages=page,
                    markets_so_far=len(all_markets),
                )
                break

        self.logger.info(
            "Kalshi discovery complete", markets_found=len(all_markets)
        )

        # Enrich categories from the events API
        await self._enrich_categories(all_markets, raw_event_tickers)
        return all_markets

    async def _enrich_categories(
        self,
        markets: List[DiscoveredMarket],
        event_tickers: Dict[str, str],
    ) -> None:
        """Fetch categories from the events API for any uncached event_tickers.

        Args:
            markets: discovered markets to update in-place.
            event_tickers: map of external_id → event_ticker from raw API data.
        """
        # Collect event_tickers that aren't cached yet
        needed = set()
        for et in event_tickers.values():
            if et and et not in self._event_category_cache:
                needed.add(et)

        # Fetch missing event data (category + title)
        if needed:
            self.logger.info(
                "Fetching event metadata",
                uncached=len(needed),
                cached=len(self._event_category_cache),
            )
        for et in needed:
            try:
                data = await self.make_request("GET", f"events/{et}")
                event = data.get("event", {})
                self._event_category_cache[et] = event.get("category", "")
                self._event_title_cache[et] = event.get("title", "")
            except Exception:
                # Non-fatal — fall back to title heuristic
                self._event_category_cache[et] = ""
                self._event_title_cache[et] = ""

        # Apply cached event data to markets
        enriched = 0
        for m in markets:
            et = event_tickers.get(m.external_id, "")
            raw_cat = self._event_category_cache.get(et, "")
            if raw_cat:
                m.category = _standardize_category(raw_cat, m.title)
                enriched += 1
            # Store event title in description for group display.
            # If the market has a subtitle (outcome-specific info like
            # "$2.10 to $2.20" or "Cardinal Parolin"), use it as the
            # title so each outcome is distinguishable when expanded.
            event_title = self._event_title_cache.get(et, "")
            if event_title:
                original_subtitle = m.description
                m.description = event_title
                if original_subtitle and original_subtitle != event_title:
                    m.title = original_subtitle
        if enriched:
            self.logger.info("Events enriched", count=enriched)

    # ------------------------------------------------------------------
    # connect() — WebSocket streaming
    # ------------------------------------------------------------------

    async def connect(
        self, tickers: Sequence[str]
    ) -> AsyncIterator[EventRecord]:
        """Stream real-time events via Kalshi WebSocket.

        Connects to the Kalshi WS API, subscribes to ticker, trade,
        and market_lifecycle_v2 channels for the given market tickers,
        and yields normalized EventRecord objects.  Reconnects
        automatically on disconnect with exponential backoff.

        The v2 lifecycle channel adds event-level lifecycle messages
        (event creation, status changes) alongside market lifecycle.

        Events are emitted with ``market_id=0`` and the market ticker
        stored in ``metadata``.  The IngestionManager is responsible
        for resolving ticker → database market_id.

        The active WebSocket reference is stored in ``self._ws`` so
        that ``update_market_subscriptions()`` can dynamically add or
        remove tickers without reconnecting.
        """
        channels = ["ticker", "trade", "market_lifecycle_v2"]
        delay = self._settings.ws_reconnect_delay
        max_delay = self._settings.ws_reconnect_max_delay

        while True:
            try:
                headers = self._ws_auth_headers()
                ws_url = self._settings.effective_kalshi_ws_url

                self.logger.info(
                    "Connecting to Kalshi WebSocket",
                    url=ws_url,
                    tickers=len(tickers),
                )

                async with websockets.connect(
                    ws_url,
                    additional_headers=headers,
                    ping_interval=self._settings.ws_ping_interval,
                    ping_timeout=self._settings.ws_ping_interval * 2,
                ) as ws:
                    # Store WS reference for dynamic subscription updates
                    self._ws = ws
                    self._subscription_ids.clear()
                    self._ws_msg_counter = 0
                    self._subscribed_tickers = set(tickers)

                    # Reset backoff on successful connection
                    delay = self._settings.ws_reconnect_delay

                    # Subscribe to channels
                    await self._send_subscribe(ws, tickers, channels)
                    self.logger.info(
                        "Subscribed to Kalshi channels",
                        channels=channels,
                        tickers=len(tickers),
                    )

                    # Message loop
                    async for raw_msg in ws:
                        try:
                            msg = json.loads(raw_msg)
                        except (json.JSONDecodeError, TypeError):
                            self.logger.warning(
                                "Non-JSON WebSocket message", raw=str(raw_msg)[:200]
                            )
                            continue

                        # Track subscription confirmations for dynamic updates
                        if msg.get("type") == "subscribed":
                            sid = (msg.get("msg") or {}).get("sid")
                            if sid is not None and sid not in self._subscription_ids:
                                self._subscription_ids.append(sid)
                            continue

                        event = self._normalize_ws_message(msg)
                        if event is not None:
                            yield event

            except websockets.exceptions.ConnectionClosed as exc:
                self.logger.warning(
                    "WebSocket connection closed",
                    code=exc.code,
                    reason=str(exc.reason)[:200],
                )
            except Exception as exc:
                self.logger.error(
                    "WebSocket error",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            finally:
                self._ws = None

            self.logger.info(
                "Reconnecting in %s seconds", delay, delay=delay
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)

    # ------------------------------------------------------------------
    # WebSocket helpers
    # ------------------------------------------------------------------

    def _ws_auth_headers(self) -> Dict[str, str]:
        """Generate authentication headers for the WebSocket handshake."""
        if not self._private_key or not self._api_key:
            return {}
        # Kalshi WS auth uses GET + the WS path for the signature
        ws_path = "/trade-api/ws/v2"
        return generate_auth_headers(
            api_key=self._api_key,
            private_key=self._private_key,
            method="GET",
            path=ws_path,
        )

    async def _send_subscribe(
        self,
        ws: Any,
        tickers: Sequence[str],
        channels: List[str],
    ) -> None:
        """Send subscription commands for the given tickers and channels."""
        # Kalshi limits subscriptions per message; batch by max_subscriptions
        max_subs = self._settings.ws_max_subscriptions
        ticker_list = list(tickers)

        for i in range(0, len(ticker_list), max_subs):
            batch = ticker_list[i : i + max_subs]
            self._ws_msg_counter += 1
            msg = {
                "id": self._ws_msg_counter,
                "cmd": "subscribe",
                "params": {
                    "channels": channels,
                    "market_tickers": batch,
                },
            }
            await ws.send(json.dumps(msg))

    def _normalize_ws_message(
        self, msg: Dict[str, Any]
    ) -> Optional[EventRecord]:
        """Convert a raw Kalshi WebSocket message to an EventRecord.

        Returns None for messages that aren't actionable events
        (e.g. subscription confirmations, pong responses).

        Handles both v1 ``market_lifecycle`` and v2
        ``market_lifecycle_v2`` message types, plus the new
        ``event_lifecycle`` messages from the v2 channel.
        """
        msg_type = msg.get("type")
        now_ms = int(time.time() * 1000)

        if msg_type == "ticker":
            return self._normalize_ticker(msg, now_ms)
        elif msg_type == "trade":
            return self._normalize_trade(msg, now_ms)
        elif msg_type in ("market_lifecycle", "market_lifecycle_v2"):
            return self._normalize_lifecycle(msg, now_ms)
        elif msg_type == "event_lifecycle":
            return self._normalize_event_lifecycle(msg, now_ms)

        # Ignore subscription acks, pongs, errors, etc.
        return None

    def _normalize_ticker(
        self, msg: Dict[str, Any], now_ms: int
    ) -> Optional[EventRecord]:
        """Normalize a ticker channel message to a PRICE_CHANGE event."""
        market_ticker = msg.get("msg", {}).get("market_ticker")
        if not market_ticker:
            return None

        payload = msg.get("msg", {})
        # Kalshi ticker channel uses _dollars suffix (Jan 2026+)
        yes_price = (
            payload.get("yes_ask_dollars")
            or payload.get("yes_bid_dollars")
            or payload.get("price_dollars")
        )
        if yes_price is None:
            return None

        price = float(yes_price)
        # _dollars values are already 0.0-1.0
        if price > 1.0:
            price /= 100.0

        return EventRecord(
            market_id=0,
            event_type=EventType.PRICE_CHANGE,
            old_value=None,
            new_value=price,
            metadata=json.dumps({
                "ticker": market_ticker,
                "yes_ask": payload.get("yes_ask_dollars"),
                "yes_bid": payload.get("yes_bid_dollars"),
                "volume": payload.get("volume_fp"),
            }),
            timestamp=now_ms,
        )

    def _normalize_trade(
        self, msg: Dict[str, Any], now_ms: int
    ) -> Optional[EventRecord]:
        """Normalize a trade channel message to a TRADE event."""
        market_ticker = msg.get("msg", {}).get("market_ticker")
        if not market_ticker:
            return None

        payload = msg.get("msg", {})
        # Kalshi trade channel uses _dollars suffix (Jan 2026+)
        yes_price = (
            payload.get("yes_price_dollars")
            or payload.get("price_dollars")
        )
        if yes_price is None:
            return None

        price = float(yes_price)
        if price > 1.0:
            price /= 100.0

        return EventRecord(
            market_id=0,
            event_type=EventType.TRADE,
            old_value=None,
            new_value=price,
            metadata=json.dumps({
                "ticker": market_ticker,
                "count": payload.get("count_fp") or payload.get("count"),
                "side": payload.get("side"),
                "taker_side": payload.get("taker_side"),
                "no_price": payload.get("no_price_dollars") or payload.get("no_price"),
            }),
            timestamp=now_ms,
        )

    def _normalize_lifecycle(
        self, msg: Dict[str, Any], now_ms: int
    ) -> Optional[EventRecord]:
        """Normalize a market lifecycle message to a STATUS_CHANGE event."""
        market_ticker = msg.get("msg", {}).get("market_ticker")
        if not market_ticker:
            return None

        payload = msg.get("msg", {})
        new_status = payload.get("status") or payload.get("result")

        return EventRecord(
            market_id=0,
            event_type=EventType.STATUS_CHANGE,
            old_value=None,
            new_value=0.0,
            metadata=json.dumps({
                "ticker": market_ticker,
                "status": new_status,
                "result": payload.get("result"),
            }),
            timestamp=now_ms,
        )

    def _normalize_event_lifecycle(
        self, msg: Dict[str, Any], now_ms: int
    ) -> Optional[EventRecord]:
        """Normalize an event lifecycle message from the v2 channel.

        Event lifecycle messages fire when Kalshi creates or updates
        events (parent containers for markets).  This enables instant
        new-market detection instead of waiting for the 60s polling cycle.

        Returns a STATUS_CHANGE event with lifecycle details in metadata.
        """
        payload = msg.get("msg", {})
        event_ticker = payload.get("event_ticker")
        if not event_ticker:
            return None

        lifecycle_type = payload.get("type") or payload.get("lifecycle_type", "unknown")

        self.logger.info(
            "Event lifecycle message",
            event_ticker=event_ticker,
            lifecycle_type=lifecycle_type,
        )

        return EventRecord(
            market_id=0,
            event_type=EventType.STATUS_CHANGE,
            old_value=None,
            new_value=0.0,
            metadata=json.dumps({
                "event_ticker": event_ticker,
                "lifecycle_type": lifecycle_type,
                "status": payload.get("status"),
                "market_ticker": payload.get("market_ticker"),
                "source": "event_lifecycle_v2",
            }),
            timestamp=now_ms,
        )

    # ------------------------------------------------------------------
    # Dynamic subscription management (Feature D)
    # ------------------------------------------------------------------

    async def update_market_subscriptions(
        self,
        add_tickers: Optional[Sequence[str]] = None,
        remove_tickers: Optional[Sequence[str]] = None,
    ) -> bool:
        """Dynamically add/remove tickers without reconnecting the WebSocket.

        Uses Kalshi's ``update_subscription`` command with the stored
        subscription IDs.  Falls back to sending a new ``subscribe``
        command if no SIDs are available.

        Returns True if the update was sent, False if no active connection.
        """
        if self._ws is None:
            return False

        try:
            if add_tickers:
                add_list = list(add_tickers)
                if self._subscription_ids:
                    # Use update_subscription with existing SIDs
                    self._ws_msg_counter += 1
                    msg = {
                        "id": self._ws_msg_counter,
                        "cmd": "update_subscription",
                        "params": {
                            "sids": list(self._subscription_ids),
                            "market_tickers": add_list,
                            "action": "add_markets",
                        },
                    }
                    await self._ws.send(json.dumps(msg))
                else:
                    # Fallback: send a new subscribe command
                    channels = ["ticker", "trade", "market_lifecycle_v2"]
                    await self._send_subscribe(self._ws, add_list, channels)

                self._subscribed_tickers.update(add_list)
                self.logger.info(
                    "Dynamic subscription add",
                    added=len(add_list),
                    total_subscribed=len(self._subscribed_tickers),
                )

            if remove_tickers:
                remove_list = list(remove_tickers)
                if self._subscription_ids:
                    self._ws_msg_counter += 1
                    msg = {
                        "id": self._ws_msg_counter,
                        "cmd": "update_subscription",
                        "params": {
                            "sids": list(self._subscription_ids),
                            "market_tickers": remove_list,
                            "action": "delete_markets",
                        },
                    }
                    await self._ws.send(json.dumps(msg))

                self._subscribed_tickers -= set(remove_list)
                self.logger.info(
                    "Dynamic subscription remove",
                    removed=len(remove_list),
                    total_subscribed=len(self._subscribed_tickers),
                )

            return True

        except Exception as exc:
            self.logger.warning(
                "Dynamic subscription update failed",
                error=str(exc),
            )
            return False

    # ------------------------------------------------------------------
    # REST: Single market lookup (Feature G)
    # ------------------------------------------------------------------

    async def get_market(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Fetch a single market by ticker via ``GET /markets/{ticker}``.

        Direct O(1) lookup instead of scanning all discovered markets.
        Useful for on-demand detail, targeted refresh after lifecycle
        events, and orderbook queries.
        """
        try:
            data = await self.make_request("GET", f"markets/{ticker}")
            return data.get("market")
        except Exception as exc:
            self.logger.warning(
                "Single market lookup failed",
                ticker=ticker,
                error=str(exc),
            )
            return None

    # ------------------------------------------------------------------
    # REST: Exchange health awareness (Feature E)
    # ------------------------------------------------------------------

    async def get_exchange_status(self) -> Optional[Dict[str, Any]]:
        """Check if the Kalshi exchange is currently operational.

        Returns the exchange status dict with fields like
        ``exchange_active`` and ``trading_active``.
        """
        try:
            return await self.make_request("GET", "exchange/status")
        except Exception as exc:
            self.logger.warning(
                "Exchange status check failed",
                error=str(exc),
            )
            return None

    async def get_exchange_schedule(self) -> Optional[Dict[str, Any]]:
        """Get the Kalshi exchange trading schedule.

        Returns schedule information including standard trading hours
        and maintenance windows.
        """
        try:
            return await self.make_request("GET", "exchange/schedule")
        except Exception as exc:
            self.logger.warning(
                "Exchange schedule fetch failed",
                error=str(exc),
            )
            return None

    # ------------------------------------------------------------------
    # REST: Candlestick / historical data (Feature C)
    # ------------------------------------------------------------------

    async def get_candlesticks(
        self,
        ticker: str,
        period_interval: int = 60,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """Fetch OHLCV candlestick data for a market.

        Uses ``GET /series/{series_ticker}/markets/{ticker}/candlesticks``
        when the series ticker can be inferred, otherwise falls back to
        ``GET /markets/{ticker}/candlesticks`` (if available).

        Args:
            ticker: Market ticker (e.g. ``AAPL-UP-100``).
            period_interval: Candle width in minutes (default 60 = 1 hour).
            start_ts: Start timestamp (Unix seconds).  Defaults to 24h ago.
            end_ts: End timestamp (Unix seconds).  Defaults to now.

        Returns:
            List of candlestick dicts with ``open``, ``high``, ``low``,
            ``close``, ``volume``, ``period_begin``, ``period_end`` fields,
            or None on failure.
        """
        now = int(time.time())
        if end_ts is None:
            end_ts = now
        if start_ts is None:
            start_ts = now - 86400  # 24 hours ago

        params: Dict[str, Any] = {
            "period_interval": period_interval,
            "start_ts": start_ts,
            "end_ts": end_ts,
        }

        # Try the series-based endpoint first (more reliable for active markets)
        series_ticker = self._infer_series_ticker(ticker)
        if series_ticker:
            try:
                data = await self.make_request(
                    "GET",
                    f"series/{series_ticker}/markets/{ticker}/candlesticks",
                    params=params,
                )
                return data.get("candlesticks", [])
            except Exception:
                pass  # Fall through to direct endpoint

        # Fallback: direct market candlesticks
        try:
            data = await self.make_request(
                "GET",
                f"markets/{ticker}/candlesticks",
                params=params,
            )
            return data.get("candlesticks", [])
        except Exception as exc:
            self.logger.warning(
                "Candlestick fetch failed",
                ticker=ticker,
                error=str(exc),
            )
            return None

    def _infer_series_ticker(self, market_ticker: str) -> Optional[str]:
        """Infer the series ticker from a market ticker.

        Kalshi tickers follow the pattern ``SERIES-OUTCOME`` (e.g.
        ``INXD-26MAR21-B5825`` belongs to series ``INXD``).  The series
        ticker is typically the first segment before the first hyphen.

        Returns None if inference is ambiguous.
        """
        parts = market_ticker.split("-")
        if len(parts) >= 2:
            return parts[0]
        return None

    async def get_series(
        self,
        series_ticker: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch series metadata.

        If ``series_ticker`` is provided, fetches a single series.
        Otherwise, returns the list of all series.
        """
        try:
            if series_ticker:
                data = await self.make_request("GET", f"series/{series_ticker}")
                return data
            else:
                data = await self.make_request("GET", "series")
                return data
        except Exception as exc:
            self.logger.warning(
                "Series fetch failed",
                series_ticker=series_ticker,
                error=str(exc),
            )
            return None

    # ------------------------------------------------------------------
    # REST: Category taxonomy (Feature F)
    # ------------------------------------------------------------------

    async def get_category_taxonomy(self) -> Optional[Dict[str, Any]]:
        """Fetch the complete Kalshi category → tag hierarchy in one call.

        Uses ``GET /search/tags_by_categories`` which returns the full
        taxonomy.  Result is cached on the adapter instance.
        """
        try:
            return await self.make_request("GET", "search/tags_by_categories")
        except Exception as exc:
            self.logger.warning(
                "Category taxonomy fetch failed",
                error=str(exc),
            )
            return None

    async def load_category_taxonomy(self) -> int:
        """Fetch the full taxonomy and populate ``_CATEGORY_MAP`` entries.

        Called once on startup to enrich the category mapping with
        Kalshi's own taxonomy.  Returns the number of new categories added.
        """
        data = await self.get_category_taxonomy()
        if not data:
            return 0

        added = 0
        categories = data.get("categories", [])
        for cat_entry in categories:
            name = cat_entry.get("name") or cat_entry.get("category", "")
            if not name:
                continue
            # Add each tag → standardized category mapping
            tags = cat_entry.get("tags", [])
            for tag in tags:
                tag_lower = str(tag).lower()
                if tag_lower not in _CATEGORY_MAP:
                    _CATEGORY_MAP[tag_lower] = name.strip().title()
                    added += 1
            # Also add the category name itself
            name_lower = name.strip().lower()
            if name_lower not in _CATEGORY_MAP:
                _CATEGORY_MAP[name_lower] = name.strip().title()
                added += 1

        if added:
            self.logger.info(
                "Category taxonomy loaded",
                new_mappings=added,
                total_mappings=len(_CATEGORY_MAP),
            )
        return added

    # ------------------------------------------------------------------
    # REST: Orderbook, trades, milestones (Feature A / B)
    # ------------------------------------------------------------------

    async def get_orderbook(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Fetch the current orderbook for a market.

        Returns bid/ask levels as ``{"orderbook": {"yes": [...], "no": [...]}}``.
        Each level is ``[price, size]``.  Used by the health score to
        compute depth imbalance and spread tightness.
        """
        try:
            return await self.make_request("GET", f"markets/{ticker}/orderbook")
        except Exception as exc:
            self.logger.debug(
                "Orderbook fetch failed",
                ticker=ticker,
                error=str(exc),
            )
            return None

    async def get_trades(
        self,
        ticker: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
        min_ts: Optional[int] = None,
        max_ts: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch recent trades, optionally filtered by market ticker.

        Returns ``{"trades": [...], "cursor": "..."}`` for pagination.
        """
        params: Dict[str, Any] = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if cursor:
            params["cursor"] = cursor
        if min_ts is not None:
            params["min_ts"] = min_ts
        if max_ts is not None:
            params["max_ts"] = max_ts

        try:
            return await self.make_request("GET", "markets/trades", params=params)
        except Exception as exc:
            self.logger.warning(
                "Trades fetch failed",
                ticker=ticker,
                error=str(exc),
            )
            return None

    async def get_milestones(
        self,
        event_ticker: Optional[str] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """Fetch milestones linked to events for resolution tracking.

        Milestones connect events to real-world data feeds (sports scores,
        economic releases).  When a milestone fires, the associated event
        is about to resolve.

        Args:
            event_ticker: Filter by specific event.  If None, returns all.
        """
        params: Dict[str, Any] = {}
        if event_ticker:
            params["event_ticker"] = event_ticker

        try:
            data = await self.make_request("GET", "milestones", params=params)
            return data.get("milestones", [])
        except Exception as exc:
            self.logger.warning(
                "Milestones fetch failed",
                error=str(exc),
            )
            return None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _normalize(self, raw: Dict[str, Any]) -> Optional[DiscoveredMarket]:
        """Convert a raw Kalshi API market object to a DiscoveredMarket."""
        external_id = raw.get("ticker") or raw.get("id")
        title = raw.get("title")
        if not external_id or not title:
            return None

        # Filter: must be tradeable and not past close time
        status = raw.get("status")
        if status not in ("active", "initialized"):
            return None
        close_time = raw.get("close_time")
        if close_time:
            try:
                ct = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
                if ct <= datetime.now(timezone.utc):
                    return None
            except (ValueError, TypeError):
                pass

        yes_price = _calculate_yes_price(raw)
        no_price = (1.0 - yes_price) if yes_price is not None else None

        volume = raw.get("volume_fp") or raw.get("volume") or raw.get("open_interest_fp") or raw.get("open_interest") or 0
        # `category` was removed from Kalshi API on Jan 5, 2026;
        # fall back to event-level fields, then derive from title
        raw_category = (
            raw.get("category")
            or raw.get("event_category")
            or raw.get("series_category")
            or ""
        )
        category = _standardize_category(raw_category, title)
        description = (
            raw.get("subtitle")
            or raw.get("yes_sub_title")
            or raw.get("description")
            or ""
        )

        return DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id=str(external_id),
            title=title,
            description=description,
            category=category,
            is_active=True,
            yes_price=yes_price,
            no_price=no_price,
            volume=float(volume),
            end_date=close_time,
        )
