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
        """Lifecycle messages (v1 type) become STATUS_CHANGE events."""
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

    def test_lifecycle_v2_message(self, kalshi_adapter):
        """Lifecycle v2 messages also become STATUS_CHANGE events."""
        msg = {
            "type": "market_lifecycle_v2",
            "msg": {
                "market_ticker": "V2-MARKET",
                "status": "closed",
                "result": "no",
            },
        }
        event = kalshi_adapter._normalize_ws_message(msg)
        assert event is not None
        assert event.event_type == EventType.STATUS_CHANGE
        meta = json.loads(event.metadata)
        assert meta["ticker"] == "V2-MARKET"
        assert meta["status"] == "closed"

    def test_event_lifecycle_message(self, kalshi_adapter):
        """Event lifecycle messages from v2 channel become STATUS_CHANGE events."""
        msg = {
            "type": "event_lifecycle",
            "msg": {
                "event_ticker": "ECON-CPI-MAR",
                "type": "event_created",
                "status": "active",
                "market_ticker": "CPI-MAR-UP-3",
            },
        }
        event = kalshi_adapter._normalize_ws_message(msg)
        assert event is not None
        assert event.event_type == EventType.STATUS_CHANGE
        assert event.market_id == 0
        meta = json.loads(event.metadata)
        assert meta["event_ticker"] == "ECON-CPI-MAR"
        assert meta["lifecycle_type"] == "event_created"
        assert meta["source"] == "event_lifecycle_v2"
        assert meta["market_ticker"] == "CPI-MAR-UP-3"

    def test_event_lifecycle_lifecycle_type_field(self, kalshi_adapter):
        """Event lifecycle uses 'lifecycle_type' field if 'type' is absent in msg."""
        msg = {
            "type": "event_lifecycle",
            "msg": {
                "event_ticker": "SPORTS-NBA-LAKERS",
                "lifecycle_type": "event_status_update",
                "status": "closed",
            },
        }
        event = kalshi_adapter._normalize_ws_message(msg)
        assert event is not None
        meta = json.loads(event.metadata)
        assert meta["lifecycle_type"] == "event_status_update"

    def test_event_lifecycle_missing_event_ticker(self, kalshi_adapter):
        """Event lifecycle without event_ticker returns None."""
        msg = {
            "type": "event_lifecycle",
            "msg": {
                "status": "active",
            },
        }
        event = kalshi_adapter._normalize_ws_message(msg)
        assert event is None

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

    async def test_subscribe_increments_msg_counter(self, kalshi_adapter):
        """Each subscribe batch increments the message counter."""
        sent_messages = []

        class FakeWS:
            async def send(self, msg):
                sent_messages.append(json.loads(msg))

        ws = FakeWS()
        kalshi_adapter._ws_msg_counter = 0
        await kalshi_adapter._send_subscribe(
            ws, ["T1", "T2"], ["ticker"]
        )

        assert kalshi_adapter._ws_msg_counter == 1
        assert sent_messages[0]["id"] == 1


class TestDynamicSubscriptions:
    """Test update_market_subscriptions for dynamic ticker management."""

    async def test_add_tickers_with_sids(self, kalshi_adapter):
        """Adding tickers with stored SIDs sends update_subscription."""
        sent_messages = []

        class FakeWS:
            async def send(self, msg):
                sent_messages.append(json.loads(msg))

        kalshi_adapter._ws = FakeWS()
        kalshi_adapter._subscription_ids = [101, 102]
        kalshi_adapter._subscribed_tickers = {"OLD-1"}

        result = await kalshi_adapter.update_market_subscriptions(
            add_tickers=["NEW-1", "NEW-2"]
        )

        assert result is True
        assert len(sent_messages) == 1
        msg = sent_messages[0]
        assert msg["cmd"] == "update_subscription"
        assert msg["params"]["action"] == "add_markets"
        assert msg["params"]["sids"] == [101, 102]
        assert set(msg["params"]["market_tickers"]) == {"NEW-1", "NEW-2"}
        # Verify subscribed_tickers is updated
        assert "NEW-1" in kalshi_adapter._subscribed_tickers
        assert "NEW-2" in kalshi_adapter._subscribed_tickers

    async def test_remove_tickers_with_sids(self, kalshi_adapter):
        """Removing tickers with stored SIDs sends delete_markets."""
        sent_messages = []

        class FakeWS:
            async def send(self, msg):
                sent_messages.append(json.loads(msg))

        kalshi_adapter._ws = FakeWS()
        kalshi_adapter._subscription_ids = [101]
        kalshi_adapter._subscribed_tickers = {"OLD-1", "OLD-2", "OLD-3"}

        result = await kalshi_adapter.update_market_subscriptions(
            remove_tickers=["OLD-2"]
        )

        assert result is True
        assert len(sent_messages) == 1
        msg = sent_messages[0]
        assert msg["cmd"] == "update_subscription"
        assert msg["params"]["action"] == "delete_markets"
        assert "OLD-2" not in kalshi_adapter._subscribed_tickers
        assert "OLD-1" in kalshi_adapter._subscribed_tickers

    async def test_add_tickers_fallback_subscribe(self, kalshi_adapter):
        """Without SIDs, adding tickers falls back to a new subscribe command."""
        sent_messages = []

        class FakeWS:
            async def send(self, msg):
                sent_messages.append(json.loads(msg))

        kalshi_adapter._ws = FakeWS()
        kalshi_adapter._subscription_ids = []  # No SIDs

        result = await kalshi_adapter.update_market_subscriptions(
            add_tickers=["FALLBACK-1"]
        )

        assert result is True
        assert len(sent_messages) == 1
        msg = sent_messages[0]
        assert msg["cmd"] == "subscribe"
        assert msg["params"]["market_tickers"] == ["FALLBACK-1"]
        assert "market_lifecycle_v2" in msg["params"]["channels"]

    async def test_no_ws_returns_false(self, kalshi_adapter):
        """Without an active WebSocket, returns False."""
        kalshi_adapter._ws = None

        result = await kalshi_adapter.update_market_subscriptions(
            add_tickers=["NEW-1"]
        )

        assert result is False

    async def test_ws_send_error_returns_false(self, kalshi_adapter):
        """If the WS send fails, returns False gracefully."""

        class BrokenWS:
            async def send(self, msg):
                raise ConnectionError("Connection lost")

        kalshi_adapter._ws = BrokenWS()
        kalshi_adapter._subscription_ids = [101]

        result = await kalshi_adapter.update_market_subscriptions(
            add_tickers=["NEW-1"]
        )

        assert result is False

    async def test_add_and_remove_simultaneously(self, kalshi_adapter):
        """Can add and remove tickers in a single call."""
        sent_messages = []

        class FakeWS:
            async def send(self, msg):
                sent_messages.append(json.loads(msg))

        kalshi_adapter._ws = FakeWS()
        kalshi_adapter._subscription_ids = [101]
        kalshi_adapter._subscribed_tickers = {"KEEP", "REMOVE"}

        result = await kalshi_adapter.update_market_subscriptions(
            add_tickers=["ADD"],
            remove_tickers=["REMOVE"],
        )

        assert result is True
        assert len(sent_messages) == 2  # One add, one remove
        add_msg = sent_messages[0]
        remove_msg = sent_messages[1]
        assert add_msg["params"]["action"] == "add_markets"
        assert remove_msg["params"]["action"] == "delete_markets"
        assert "ADD" in kalshi_adapter._subscribed_tickers
        assert "REMOVE" not in kalshi_adapter._subscribed_tickers


class TestSubscriptionIdTracking:
    """Test that subscription IDs are extracted from confirmation messages."""

    def test_initial_state(self, kalshi_adapter):
        """Adapter starts with empty subscription state."""
        assert kalshi_adapter._subscription_ids == []
        assert kalshi_adapter._ws is None
        assert kalshi_adapter._ws_msg_counter == 0
        assert kalshi_adapter._subscribed_tickers == set()


class TestExchangeHealth:
    """Test exchange status and schedule methods exist with correct interface."""

    async def test_get_exchange_status_exists(self, kalshi_adapter):
        """get_exchange_status method is available."""
        assert hasattr(kalshi_adapter, "get_exchange_status")

    async def test_get_exchange_schedule_exists(self, kalshi_adapter):
        """get_exchange_schedule method is available."""
        assert hasattr(kalshi_adapter, "get_exchange_schedule")


class TestSingleMarketLookup:
    """Test get_market method interface."""

    async def test_get_market_exists(self, kalshi_adapter):
        """get_market method is available."""
        assert hasattr(kalshi_adapter, "get_market")
