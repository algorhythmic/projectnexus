"""Kalshi prediction market adapter.

Implements the BaseAdapter interface for the Kalshi exchange.
Phase 1 (Milestone 1.1): REST-based market discovery with RSA-PSS auth.
Phase 1 (Milestone 1.2): WebSocket streaming (connect method).
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence

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
    """Map a Kalshi category string to a standardized name."""
    if raw:
        mapped = _CATEGORY_MAP.get(raw.strip().lower())
        if mapped:
            return mapped
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
        - min_close_ts: skip markets closing in <1h (about to expire)
        - mve_filter=exclude: skip multivariate combo markets (they have
          very long titles like "yes A,yes B,yes C" and rarely trade)
        """
        all_markets: List[DiscoveredMarket] = []
        # Map external_id → event_ticker for category enrichment
        raw_event_tickers: Dict[str, str] = {}
        cursor: Optional[str] = None
        max_pages = self._settings.kalshi_discovery_max_pages
        page = 0

        # Only discover markets closing more than 1 hour from now
        min_close = int(time.time()) + 3600

        while True:
            params: Dict[str, Any] = {
                "limit": 200,
                "status": "open",
                "min_close_ts": min_close,
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
            # Store event title in description for group display,
            # but preserve the market subtitle as the title when the
            # market title matches the event title (multi-outcome markets
            # where each outcome has a unique subtitle but shares the
            # event question as its title).
            event_title = self._event_title_cache.get(et, "")
            if event_title:
                original_subtitle = m.description
                m.description = event_title
                if (
                    original_subtitle
                    and original_subtitle != event_title
                    and m.title == event_title
                ):
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

        Connects to the Kalshi WS API, subscribes to ticker and trade
        channels for the given market tickers, and yields normalized
        EventRecord objects.  Reconnects automatically on disconnect
        with exponential backoff.

        Events are emitted with ``market_id=0`` and the market ticker
        stored in ``metadata``.  The IngestionManager is responsible
        for resolving ticker → database market_id.
        """
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
                    # Reset backoff on successful connection
                    delay = self._settings.ws_reconnect_delay

                    # Subscribe to channels
                    await self._send_subscribe(ws, tickers, ["ticker", "trade", "market_lifecycle"])
                    self.logger.info(
                        "Subscribed to Kalshi channels",
                        channels=["ticker", "trade", "market_lifecycle"],
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
            msg = {
                "id": i + 1,
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
        """
        msg_type = msg.get("type")
        now_ms = int(time.time() * 1000)

        if msg_type == "ticker":
            return self._normalize_ticker(msg, now_ms)
        elif msg_type == "trade":
            return self._normalize_trade(msg, now_ms)
        elif msg_type == "market_lifecycle":
            return self._normalize_lifecycle(msg, now_ms)

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
        description = raw.get("subtitle") or raw.get("description") or ""

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
