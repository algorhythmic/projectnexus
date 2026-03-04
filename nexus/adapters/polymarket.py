"""Polymarket prediction market adapter.

Implements the BaseAdapter interface for Polymarket.
Phase 3 (Milestone 3.1): REST-based market discovery via Gamma API +
WebSocket streaming via CLOB market channel. No authentication required
for read-only access.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence

import websockets
import websockets.exceptions

from nexus.adapters.base import BaseAdapter
from nexus.core.config import Settings
from nexus.core.types import DiscoveredMarket, EventRecord, EventType, Platform

# Mapping of Polymarket categories to standardized names
_CATEGORY_MAP: Dict[str, str] = {
    "Politics": "Politics",
    "Crypto": "Cryptocurrency",
    "Economics": "Economics",
    "Sports": "Sports",
    "Pop Culture": "Entertainment",
    "Business": "Business",
    "Science": "Science",
    "Technology": "Technology",
    "Gaming": "Entertainment",
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
    """Map a Polymarket category string to a standardized name."""
    if raw:
        clean = raw.strip()
        mapped = _CATEGORY_MAP.get(clean)
        if mapped:
            return mapped
    return _categorize_from_title(title)


def _calculate_yes_price(market: Dict[str, Any]) -> Optional[float]:
    """Extract yes price from a Polymarket market object.

    Polymarket prices are already in 0.0-1.0 range.
    Priority: outcomePrices[0] > lastTradePrice > bestBid/bestAsk midpoint.
    """
    # Try outcomePrices first (JSON-encoded string)
    outcome_prices_str = market.get("outcomePrices")
    if outcome_prices_str:
        try:
            prices = json.loads(outcome_prices_str)
            if prices and len(prices) >= 1:
                return max(0.0, min(1.0, float(prices[0])))
        except (json.JSONDecodeError, TypeError, ValueError, IndexError):
            pass

    # Fall back to lastTradePrice
    ltp = market.get("lastTradePrice")
    if ltp is not None:
        try:
            return max(0.0, min(1.0, float(ltp)))
        except (ValueError, TypeError):
            pass

    # Fall back to bid/ask midpoint
    bid = market.get("bestBid")
    ask = market.get("bestAsk")
    if bid is not None and ask is not None:
        try:
            return max(0.0, min(1.0, (float(bid) + float(ask)) / 2.0))
        except (ValueError, TypeError):
            pass

    return None


class PolymarketAdapter(BaseAdapter):
    """Adapter for the Polymarket prediction market platform.

    Discovery uses the Gamma API (REST, no auth required).
    Streaming uses the CLOB WebSocket market channel (no auth required).
    Subscriptions use token_ids (not condition_ids), so the adapter
    maintains an internal token_id -> condition_id mapping.
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__(
            base_url=settings.polymarket_base_url,
            rate_limit=settings.polymarket_reads_per_second,
            timeout=settings.request_timeout,
        )
        self._settings = settings
        # token_id -> condition_id mapping for WS event resolution
        self._token_to_condition: Dict[str, str] = {}
        # condition_id -> token_ids for subscription
        self._condition_to_tokens: Dict[str, List[str]] = {}

    # ------------------------------------------------------------------
    # Discovery (REST)
    # ------------------------------------------------------------------

    async def discover(self) -> List[DiscoveredMarket]:
        """Enumerate active markets via offset-paginated Gamma API calls."""
        all_markets: List[DiscoveredMarket] = []
        offset = 0
        page_size = self._settings.polymarket_discovery_page_size

        while True:
            params: Dict[str, Any] = {
                "limit": page_size,
                "offset": offset,
                "active": "true",
                "closed": "false",
            }

            data = await self.make_request("GET", "markets", params=params)

            # Gamma API returns a list directly
            raw_markets = data if isinstance(data, list) else []
            if not raw_markets:
                break

            for raw in raw_markets:
                market = self._normalize(raw)
                if market is not None:
                    all_markets.append(market)
                self._build_token_mapping(raw)

            if len(raw_markets) < page_size:
                break
            offset += page_size

        self.logger.info(
            "Polymarket discovery complete",
            markets_found=len(all_markets),
            token_mappings=len(self._token_to_condition),
        )
        return all_markets

    def _normalize(self, raw: Dict[str, Any]) -> Optional[DiscoveredMarket]:
        """Convert a raw Polymarket Gamma API market to DiscoveredMarket."""
        condition_id = raw.get("conditionId")
        title = raw.get("question")
        if not condition_id or not title:
            return None

        if not raw.get("active", False):
            return None
        if raw.get("closed", False):
            return None

        end_date_str = raw.get("endDate")
        if end_date_str:
            try:
                ed = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                if ed <= datetime.now(timezone.utc):
                    return None
            except (ValueError, TypeError):
                pass

        yes_price = _calculate_yes_price(raw)
        no_price = (1.0 - yes_price) if yes_price is not None else None

        volume = raw.get("volume") or 0
        category = _standardize_category(raw.get("category"), title)
        description = raw.get("description") or ""

        return DiscoveredMarket(
            platform=Platform.POLYMARKET,
            external_id=str(condition_id),
            title=title,
            description=description[:500],
            category=category,
            is_active=True,
            yes_price=yes_price,
            no_price=no_price,
            volume=float(volume),
            end_date=end_date_str,
            raw_data=raw,
        )

    def _build_token_mapping(self, raw: Dict[str, Any]) -> None:
        """Parse clobTokenIds and map token_ids back to conditionId."""
        condition_id = raw.get("conditionId")
        clob_tokens_str = raw.get("clobTokenIds")
        if not condition_id or not clob_tokens_str:
            return

        try:
            token_ids = json.loads(clob_tokens_str)
        except (json.JSONDecodeError, TypeError):
            return

        if not isinstance(token_ids, list):
            return

        self._condition_to_tokens[condition_id] = token_ids
        for token_id in token_ids:
            self._token_to_condition[token_id] = condition_id

    # ------------------------------------------------------------------
    # Streaming (WebSocket)
    # ------------------------------------------------------------------

    async def connect(
        self, tickers: Sequence[str]
    ) -> AsyncIterator[EventRecord]:
        """Stream real-time events via Polymarket CLOB WebSocket.

        Connects to the WS market channel, subscribes by token_id
        (resolved from condition_id tickers), and yields normalized
        EventRecord objects with market_id=0 and condition_id in metadata.
        """
        delay = self._settings.ws_reconnect_delay
        max_delay = self._settings.ws_reconnect_max_delay

        while True:
            try:
                ws_url = self._settings.polymarket_ws_url

                token_ids = self._resolve_tickers_to_tokens(tickers)
                if not token_ids:
                    self.logger.warning(
                        "No token_ids resolved — waiting for discovery",
                        tickers=len(tickers),
                    )
                    await asyncio.sleep(
                        self._settings.discovery_interval_seconds
                    )
                    continue

                self.logger.info(
                    "Connecting to Polymarket WebSocket",
                    url=ws_url,
                    tokens=len(token_ids),
                )

                async with websockets.connect(
                    ws_url,
                    ping_interval=None,
                    ping_timeout=None,
                ) as ws:
                    delay = self._settings.ws_reconnect_delay

                    await self._send_subscribe(ws, token_ids)
                    self.logger.info(
                        "Subscribed to Polymarket market channel",
                        tokens=len(token_ids),
                    )

                    heartbeat_task = asyncio.create_task(
                        self._heartbeat_loop(ws)
                    )

                    try:
                        async for raw_msg in ws:
                            if isinstance(raw_msg, str) and raw_msg.strip() == "PONG":
                                continue

                            try:
                                msg = json.loads(raw_msg)
                            except (json.JSONDecodeError, TypeError):
                                continue

                            events = self._normalize_ws_message(msg)
                            for event in events:
                                yield event
                    finally:
                        heartbeat_task.cancel()
                        try:
                            await heartbeat_task
                        except asyncio.CancelledError:
                            pass

            except websockets.exceptions.ConnectionClosed as exc:
                self.logger.warning(
                    "Polymarket WebSocket closed",
                    code=exc.code,
                    reason=str(exc.reason)[:200],
                )
            except Exception as exc:
                self.logger.error(
                    "Polymarket WebSocket error",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )

            self.logger.info("Reconnecting in %s seconds", delay, delay=delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)

    def _resolve_tickers_to_tokens(
        self, tickers: Sequence[str]
    ) -> List[str]:
        """Resolve condition_id tickers to token_ids for WS subscription."""
        token_ids: List[str] = []
        for ticker in tickers:
            tokens = self._condition_to_tokens.get(ticker, [])
            token_ids.extend(tokens)
        return token_ids

    async def _send_subscribe(
        self, ws: Any, token_ids: List[str]
    ) -> None:
        """Send subscription message for the given token_ids."""
        msg = {
            "assets_ids": token_ids,
            "type": "market",
            "custom_feature_enabled": True,
        }
        await ws.send(json.dumps(msg))

    async def _heartbeat_loop(self, ws: Any) -> None:
        """Send PING heartbeat every N seconds as required by Polymarket."""
        interval = self._settings.polymarket_ws_ping_interval
        while True:
            try:
                await ws.send("PING")
            except Exception:
                break
            await asyncio.sleep(interval)

    # ------------------------------------------------------------------
    # WS message normalization
    # ------------------------------------------------------------------

    def _normalize_ws_message(
        self, msg: Dict[str, Any]
    ) -> List[EventRecord]:
        """Convert a raw Polymarket WS message to EventRecord(s)."""
        msg_type = msg.get("event_type") or msg.get("type")
        now_ms = int(time.time() * 1000)

        if msg_type == "last_trade_price":
            event = self._normalize_trade(msg, now_ms)
            return [event] if event else []
        elif msg_type == "price_change":
            return self._normalize_price_change(msg, now_ms)
        elif msg_type == "new_market":
            event = self._normalize_new_market(msg, now_ms)
            return [event] if event else []

        return []

    def _normalize_trade(
        self, msg: Dict[str, Any], now_ms: int
    ) -> Optional[EventRecord]:
        """Normalize a last_trade_price message to a TRADE event."""
        asset_id = msg.get("asset_id")
        if not asset_id:
            return None

        condition_id = self._token_to_condition.get(asset_id)
        if not condition_id:
            return None

        price = msg.get("price")
        if price is None:
            return None

        try:
            price_float = float(price)
        except (ValueError, TypeError):
            return None

        return EventRecord(
            market_id=0,
            event_type=EventType.TRADE,
            old_value=None,
            new_value=price_float,
            metadata=json.dumps({
                "ticker": condition_id,
                "asset_id": asset_id,
                "size": msg.get("size"),
                "side": msg.get("side"),
            }),
            timestamp=now_ms,
        )

    def _normalize_price_change(
        self, msg: Dict[str, Any], now_ms: int
    ) -> List[EventRecord]:
        """Normalize a price_change message to PRICE_CHANGE events."""
        events: List[EventRecord] = []
        changes = msg.get("price_changes") or []

        for change in changes:
            asset_id = change.get("asset_id")
            if not asset_id:
                continue

            condition_id = self._token_to_condition.get(asset_id)
            if not condition_id:
                continue

            best_bid = change.get("best_bid") or change.get("price")
            best_ask = change.get("best_ask")

            if best_bid is not None and best_ask is not None:
                try:
                    price = (float(best_bid) + float(best_ask)) / 2.0
                except (ValueError, TypeError):
                    continue
            elif best_bid is not None:
                try:
                    price = float(best_bid)
                except (ValueError, TypeError):
                    continue
            else:
                continue

            events.append(EventRecord(
                market_id=0,
                event_type=EventType.PRICE_CHANGE,
                old_value=None,
                new_value=price,
                metadata=json.dumps({
                    "ticker": condition_id,
                    "asset_id": asset_id,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                }),
                timestamp=now_ms,
            ))

        return events

    def _normalize_new_market(
        self, msg: Dict[str, Any], now_ms: int
    ) -> Optional[EventRecord]:
        """Normalize a new_market notification."""
        market_id_field = msg.get("market") or msg.get("id")
        if not market_id_field:
            return None

        return EventRecord(
            market_id=0,
            event_type=EventType.NEW_MARKET,
            old_value=None,
            new_value=0.0,
            metadata=json.dumps({
                "ticker": str(market_id_field),
                "source": "polymarket_ws",
            }),
            timestamp=now_ms,
        )
