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

# Mapping of Kalshi categories to standardized names
_CATEGORY_MAP: Dict[str, str] = {
    "Economics": "Economics",
    "Politics": "Politics",
    "Elections": "Politics",
    "Weather": "Weather",
    "Sports": "Sports",
    "Entertainment": "Entertainment",
    "Technology": "Technology",
    "Science": "Science",
    "Business": "Business",
    "Crypto": "Cryptocurrency",
    "Cryptocurrency": "Cryptocurrency",
    "Climate": "Weather",
    "Financial": "Economics",
    "Culture": "Entertainment",
}


def _categorize_from_title(title: str) -> str:
    """Categorize a market based on title keywords."""
    t = title.lower()
    if any(w in t for w in ("election", "president", "congress", "senate", "vote", "poll")):
        return "Politics"
    if any(w in t for w in ("bitcoin", "crypto", "ethereum", "btc", "eth")):
        return "Cryptocurrency"
    if any(w in t for w in ("gdp", "inflation", "fed", "economy", "unemployment", "interest rate")):
        return "Economics"
    if any(w in t for w in ("nfl", "nba", "mlb", "nhl", "super bowl", "world cup")):
        return "Sports"
    if any(w in t for w in ("temperature", "weather", "hurricane", "rain")):
        return "Weather"
    if any(w in t for w in ("movie", "oscar", "emmy", "celebrity")):
        return "Entertainment"
    if any(w in t for w in ("stock", "company", "ipo", "earnings")):
        return "Business"
    return "Other"


def _standardize_category(raw: Optional[str], title: str) -> str:
    """Map a Kalshi category string to a standardized name."""
    if raw:
        clean = raw.strip().title()
        mapped = _CATEGORY_MAP.get(clean)
        if mapped:
            return mapped
    return _categorize_from_title(title)


def _calculate_yes_price(market: Dict[str, Any]) -> Optional[float]:
    """Extract the yes price from a Kalshi market object."""
    raw = (
        market.get("yes_ask")
        or market.get("yes_bid")
        or market.get("last_price")
    )
    if raw is None:
        return None
    price = float(raw)
    # Kalshi reports prices in cents (0-100); normalize to 0-1
    if price > 1.0:
        price /= 100.0
    return max(0.0, min(1.0, price))


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
        """Enumerate all active markets via cursor-paginated REST calls."""
        all_markets: List[DiscoveredMarket] = []
        cursor: Optional[str] = None
        max_pages = self._settings.kalshi_discovery_max_pages
        page = 0

        while True:
            params: Dict[str, Any] = {"limit": 200, "status": "open"}
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
        return all_markets

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
                    await self._send_subscribe(ws, tickers, ["ticker", "trade"])
                    self.logger.info(
                        "Subscribed to Kalshi channels",
                        channels=["ticker", "trade"],
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
        yes_price = payload.get("yes_ask") or payload.get("yes_bid") or payload.get("last_price")
        if yes_price is None:
            return None

        price = float(yes_price)
        if price > 1.0:
            price /= 100.0

        return EventRecord(
            market_id=0,
            event_type=EventType.PRICE_CHANGE,
            old_value=None,
            new_value=price,
            metadata=json.dumps({
                "ticker": market_ticker,
                "yes_ask": payload.get("yes_ask"),
                "yes_bid": payload.get("yes_bid"),
                "no_ask": payload.get("no_ask"),
                "no_bid": payload.get("no_bid"),
                "volume": payload.get("volume"),
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
        yes_price = payload.get("yes_price")
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
                "count": payload.get("count"),
                "side": payload.get("side"),
                "taker_side": payload.get("taker_side"),
                "no_price": payload.get("no_price"),
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

        # Filter: must be open and not past close time
        status = raw.get("status")
        if status not in ("active", "open", "initialized"):
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

        volume = raw.get("volume") or raw.get("open_interest") or 0
        category = _standardize_category(raw.get("category"), title)
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
            raw_data=raw,
        )
