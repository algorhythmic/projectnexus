"""Tests for Kalshi WebSocket message normalization and auth."""

import json
import time

import pytest

from nexus.adapters.kalshi import KalshiAdapter
from nexus.core.config import Settings
from nexus.core.types import EventType


@pytest.fixture
def kalshi_adapter():
    """Create a KalshiAdapter with test settings (no real API key)."""
    s = Settings(
        kalshi_api_key="test-key",
        kalshi_private_key_path="",
        kalshi_use_demo=True,
    )
    return KalshiAdapter(s)


class TestNormalizeWsMessage:
    """Test _normalize_ws_message for various message types."""

    def test_ticker_message(self, kalshi_adapter):
        """Ticker messages become PRICE_CHANGE events."""
        msg = {
            "type": "ticker",
            "msg": {
                "market_ticker": "AAPL-UP-100",
                "yes_ask_dollars": "0.6500",
                "yes_bid_dollars": "0.6300",
                "price_dollars": "0.6400",
                "volume_fp": "1200.00",
            },
        }
        event = kalshi_adapter._normalize_ws_message(msg)
        assert event is not None
        assert event.event_type == EventType.PRICE_CHANGE
        assert event.market_id == 0
        assert event.new_value == 0.65
        meta = json.loads(event.metadata)
        assert meta["ticker"] == "AAPL-UP-100"
        assert meta["volume"] == "1200.00"

    def test_ticker_message_decimal_price(self, kalshi_adapter):
        """Ticker with _dollars price is parsed correctly."""
        msg = {
            "type": "ticker",
            "msg": {
                "market_ticker": "BTC-50K",
                "yes_ask_dollars": "0.4500",
            },
        }
        event = kalshi_adapter._normalize_ws_message(msg)
        assert event is not None
        assert event.new_value == 0.45

    def test_ticker_missing_price(self, kalshi_adapter):
        """Ticker message with no price fields returns None."""
        msg = {
            "type": "ticker",
            "msg": {
                "market_ticker": "NO-PRICE",
            },
        }
        event = kalshi_adapter._normalize_ws_message(msg)
        assert event is None

    def test_ticker_missing_market_ticker(self, kalshi_adapter):
        """Ticker message without market_ticker returns None."""
        msg = {
            "type": "ticker",
            "msg": {
                "yes_ask": 50,
            },
        }
        event = kalshi_adapter._normalize_ws_message(msg)
        assert event is None

    def test_trade_message(self, kalshi_adapter):
        """Trade messages become TRADE events."""
        msg = {
            "type": "trade",
            "msg": {
                "market_ticker": "ELECTION-2024",
                "yes_price_dollars": "0.5500",
                "count_fp": "10.00",
                "side": "yes",
                "taker_side": "yes",
                "no_price_dollars": "0.4500",
            },
        }
        event = kalshi_adapter._normalize_ws_message(msg)
        assert event is not None
        assert event.event_type == EventType.TRADE
        assert event.market_id == 0
        assert event.new_value == 0.55
        meta = json.loads(event.metadata)
        assert meta["ticker"] == "ELECTION-2024"
        assert meta["count"] == "10.00"
        assert meta["side"] == "yes"

    def test_trade_missing_price(self, kalshi_adapter):
        """Trade message without yes_price returns None."""
        msg = {
            "type": "trade",
            "msg": {
                "market_ticker": "MISSING",
            },
        }
        event = kalshi_adapter._normalize_ws_message(msg)
        assert event is None

    def test_lifecycle_message(self, kalshi_adapter):
        """Lifecycle messages become STATUS_CHANGE events."""
        msg = {
            "type": "market_lifecycle",
            "msg": {
                "market_ticker": "SETTLE-MARKET",
                "status": "settled",
                "result": "yes",
            },
        }
        event = kalshi_adapter._normalize_ws_message(msg)
        assert event is not None
        assert event.event_type == EventType.STATUS_CHANGE
        assert event.market_id == 0
        meta = json.loads(event.metadata)
        assert meta["ticker"] == "SETTLE-MARKET"
        assert meta["status"] == "settled"
        assert meta["result"] == "yes"

    def test_subscription_ack_ignored(self, kalshi_adapter):
        """Subscription confirmation messages return None."""
        msg = {
            "id": 1,
            "type": "subscribed",
            "msg": {},
        }
        event = kalshi_adapter._normalize_ws_message(msg)
        assert event is None

    def test_pong_ignored(self, kalshi_adapter):
        """Pong messages return None."""
        msg = {"type": "pong"}
        event = kalshi_adapter._normalize_ws_message(msg)
        assert event is None

    def test_unknown_type_ignored(self, kalshi_adapter):
        """Unknown message types return None."""
        msg = {"type": "something_new", "data": {}}
        event = kalshi_adapter._normalize_ws_message(msg)
        assert event is None


class TestWsAuthHeaders:
    """Test WebSocket auth header generation."""

    def test_no_key_returns_empty(self, kalshi_adapter):
        """Without a loaded private key, _ws_auth_headers returns empty dict."""
        # kalshi_adapter has no private key loaded (empty path)
        headers = kalshi_adapter._ws_auth_headers()
        assert headers == {}

    def test_with_key_returns_headers(self, rsa_key_pair):
        """With a loaded key, _ws_auth_headers returns auth headers."""
        private_key, _ = rsa_key_pair
        s = Settings(
            kalshi_api_key="test-key",
            kalshi_private_key_path="",
            kalshi_use_demo=True,
        )
        adapter = KalshiAdapter(s)
        adapter._private_key = private_key
        headers = adapter._ws_auth_headers()
        assert "KALSHI-ACCESS-KEY" in headers
        assert headers["KALSHI-ACCESS-KEY"] == "test-key"
        assert "KALSHI-ACCESS-TIMESTAMP" in headers
        assert "KALSHI-ACCESS-SIGNATURE" in headers


class TestSubscribeMessage:
    """Test _send_subscribe message format."""

    async def test_subscribe_format(self, kalshi_adapter):
        """_send_subscribe sends correctly formatted JSON."""
        sent_messages = []

        class FakeWS:
            async def send(self, msg):
                sent_messages.append(json.loads(msg))

        ws = FakeWS()
        await kalshi_adapter._send_subscribe(
            ws, ["TICKER-1", "TICKER-2"], ["ticker", "trade"]
        )

        assert len(sent_messages) == 1
        msg = sent_messages[0]
        assert msg["cmd"] == "subscribe"
        assert msg["params"]["channels"] == ["ticker", "trade"]
        assert msg["params"]["market_tickers"] == ["TICKER-1", "TICKER-2"]

    async def test_subscribe_batching(self):
        """Large ticker lists are batched by ws_max_subscriptions."""
        s = Settings(
            kalshi_api_key="",
            kalshi_private_key_path="",
            ws_max_subscriptions=2,
        )
        adapter = KalshiAdapter(s)

        sent_messages = []

        class FakeWS:
            async def send(self, msg):
                sent_messages.append(json.loads(msg))

        ws = FakeWS()
        await adapter._send_subscribe(
            ws, ["T1", "T2", "T3", "T4", "T5"], ["ticker"]
        )

        # 5 tickers / 2 per batch = 3 messages
        assert len(sent_messages) == 3
        assert sent_messages[0]["params"]["market_tickers"] == ["T1", "T2"]
        assert sent_messages[1]["params"]["market_tickers"] == ["T3", "T4"]
        assert sent_messages[2]["params"]["market_tickers"] == ["T5"]
