"""Tests for PolymarketAdapter — REST normalization, token mapping, and WS messages."""

import asyncio
import json

import pytest

from nexus.adapters.polymarket import (
    PolymarketAdapter,
    _calculate_yes_price,
    _categorize_from_title,
    _standardize_category,
)
from nexus.core.config import Settings
from nexus.core.types import EventType, Platform


@pytest.fixture
def adapter():
    """PolymarketAdapter with test settings."""
    s = Settings(
        kalshi_api_key="",
        kalshi_private_key_path="",
        polymarket_enabled=True,
    )
    return PolymarketAdapter(s)


def _valid_market(**overrides):
    """Build a valid Polymarket Gamma API market dict."""
    base = {
        "conditionId": "0xabc123",
        "question": "Will BTC reach $100k?",
        "description": "Bitcoin price prediction",
        "outcomePrices": '["0.65","0.35"]',
        "clobTokenIds": '["tok_yes","tok_no"]',
        "volume": 50000,
        "bestBid": 0.63,
        "bestAsk": 0.67,
        "lastTradePrice": 0.65,
        "active": True,
        "closed": False,
        "endDate": "2027-12-31T00:00:00Z",
        "category": "Crypto",
    }
    base.update(overrides)
    return base


class TestPolymarketNormalize:
    def test_valid_market(self, adapter):
        """Valid market normalizes to DiscoveredMarket."""
        market = adapter._normalize(_valid_market())
        assert market is not None
        assert market.platform == Platform.POLYMARKET
        assert market.external_id == "0xabc123"
        assert market.title == "Will BTC reach $100k?"
        assert market.yes_price == 0.65
        assert market.category == "Cryptocurrency"

    def test_missing_condition_id(self, adapter):
        """Missing conditionId returns None."""
        raw = _valid_market()
        del raw["conditionId"]
        assert adapter._normalize(raw) is None

    def test_missing_question(self, adapter):
        """Missing question returns None."""
        raw = _valid_market()
        del raw["question"]
        assert adapter._normalize(raw) is None

    def test_closed_market_filtered(self, adapter):
        """Closed market is filtered out."""
        assert adapter._normalize(_valid_market(closed=True)) is None

    def test_inactive_market_filtered(self, adapter):
        """Inactive market is filtered out."""
        assert adapter._normalize(_valid_market(active=False)) is None

    def test_past_end_date_filtered(self, adapter):
        """Market with past endDate is filtered out."""
        assert adapter._normalize(
            _valid_market(endDate="2020-01-01T00:00:00Z")
        ) is None

    def test_no_price(self, adapter):
        """Market with no price data still normalizes."""
        raw = _valid_market()
        del raw["outcomePrices"]
        del raw["lastTradePrice"]
        del raw["bestBid"]
        del raw["bestAsk"]
        market = adapter._normalize(raw)
        assert market is not None
        assert market.yes_price is None


class TestPriceCalculation:
    def test_from_outcome_prices(self):
        """Price extracted from outcomePrices JSON string."""
        assert _calculate_yes_price({"outcomePrices": '["0.73","0.27"]'}) == 0.73

    def test_from_last_trade_price(self):
        """Falls back to lastTradePrice."""
        assert _calculate_yes_price({"lastTradePrice": "0.42"}) == 0.42

    def test_from_bid_ask_midpoint(self):
        """Falls back to bid/ask midpoint."""
        price = _calculate_yes_price({"bestBid": 0.40, "bestAsk": 0.50})
        assert abs(price - 0.45) < 0.001

    def test_clamped_to_range(self):
        """Price is clamped to 0.0-1.0."""
        assert _calculate_yes_price({"outcomePrices": '["1.5","0.0"]'}) == 1.0
        assert _calculate_yes_price({"outcomePrices": '["-0.1","1.1"]'}) == 0.0

    def test_invalid_json_returns_none(self):
        """Invalid outcomePrices returns None."""
        assert _calculate_yes_price({"outcomePrices": "not json"}) is None

    def test_no_price_data(self):
        """No price fields returns None."""
        assert _calculate_yes_price({}) is None


class TestCategoryMapping:
    def test_known_category(self):
        assert _standardize_category("Crypto", "test") == "Cryptocurrency"
        assert _standardize_category("Pop Culture", "test") == "Entertainment"
        assert _standardize_category("Politics", "test") == "Politics"

    def test_title_fallback(self):
        assert _categorize_from_title("Will Bitcoin reach $100k?") == "Cryptocurrency"
        assert _categorize_from_title("US Presidential Election") == "Politics"
        assert _categorize_from_title("NFL Super Bowl winner") == "Sports"
        assert _categorize_from_title("Some random thing") == "Other"


class TestTokenMapping:
    def test_build_token_mapping(self, adapter):
        """Build token mapping from raw market data."""
        raw = {
            "conditionId": "cond_abc",
            "clobTokenIds": '["tok_yes","tok_no"]',
        }
        adapter._build_token_mapping(raw)
        assert adapter._token_to_condition["tok_yes"] == "cond_abc"
        assert adapter._token_to_condition["tok_no"] == "cond_abc"
        assert adapter._condition_to_tokens["cond_abc"] == ["tok_yes", "tok_no"]

    def test_resolve_tickers_to_tokens(self, adapter):
        """Resolve condition_ids to token_ids."""
        adapter._condition_to_tokens = {
            "cond1": ["tok1a", "tok1b"],
            "cond2": ["tok2a"],
        }
        tokens = adapter._resolve_tickers_to_tokens(["cond1", "cond2"])
        assert set(tokens) == {"tok1a", "tok1b", "tok2a"}

    def test_resolve_unknown_ticker(self, adapter):
        """Unknown ticker returns empty list."""
        assert adapter._resolve_tickers_to_tokens(["unknown"]) == []

    def test_missing_clob_tokens(self, adapter):
        """Missing clobTokenIds gracefully skipped."""
        adapter._build_token_mapping({"conditionId": "cond"})
        assert "cond" not in adapter._condition_to_tokens

    def test_invalid_json_tokens(self, adapter):
        """Invalid JSON clobTokenIds gracefully skipped."""
        adapter._build_token_mapping({
            "conditionId": "cond",
            "clobTokenIds": "not json",
        })
        assert "cond" not in adapter._condition_to_tokens


class TestWsNormalize:
    def test_trade_message(self, adapter):
        """last_trade_price normalizes to TRADE event."""
        adapter._token_to_condition = {"tok1": "cond1"}
        msg = {
            "event_type": "last_trade_price",
            "asset_id": "tok1",
            "price": "0.72",
            "size": "100",
            "side": "BUY",
        }
        events = adapter._normalize_ws_message(msg)
        assert len(events) == 1
        assert events[0].event_type == EventType.TRADE
        assert events[0].market_id == 0
        assert events[0].new_value == 0.72
        meta = json.loads(events[0].metadata)
        assert meta["ticker"] == "cond1"
        assert meta["asset_id"] == "tok1"

    def test_price_change_message(self, adapter):
        """price_change normalizes to PRICE_CHANGE events."""
        adapter._token_to_condition = {"tokA": "condA", "tokB": "condB"}
        msg = {
            "event_type": "price_change",
            "price_changes": [
                {"asset_id": "tokA", "best_bid": "0.60", "best_ask": "0.62"},
                {"asset_id": "tokB", "best_bid": "0.40", "best_ask": "0.42"},
            ],
        }
        events = adapter._normalize_ws_message(msg)
        assert len(events) == 2
        assert events[0].event_type == EventType.PRICE_CHANGE
        assert abs(events[0].new_value - 0.61) < 0.001
        assert abs(events[1].new_value - 0.41) < 0.001

    def test_price_change_bid_only(self, adapter):
        """price_change with only best_bid uses bid as price."""
        adapter._token_to_condition = {"tok1": "cond1"}
        msg = {
            "event_type": "price_change",
            "price_changes": [
                {"asset_id": "tok1", "best_bid": "0.55"},
            ],
        }
        events = adapter._normalize_ws_message(msg)
        assert len(events) == 1
        assert events[0].new_value == 0.55

    def test_unknown_asset_id_skipped(self, adapter):
        """Unknown asset_id produces no events."""
        adapter._token_to_condition = {}
        msg = {
            "event_type": "last_trade_price",
            "asset_id": "unknown",
            "price": "0.50",
        }
        assert adapter._normalize_ws_message(msg) == []

    def test_unknown_message_type_ignored(self, adapter):
        """Unhandled message type produces no events."""
        msg = {"event_type": "tick_size_change", "data": {}}
        assert adapter._normalize_ws_message(msg) == []

    def test_new_market_message(self, adapter):
        """new_market notification normalizes to NEW_MARKET event."""
        msg = {"event_type": "new_market", "market": "new_cond_123"}
        events = adapter._normalize_ws_message(msg)
        assert len(events) == 1
        assert events[0].event_type == EventType.NEW_MARKET
        meta = json.loads(events[0].metadata)
        assert meta["ticker"] == "new_cond_123"

    def test_trade_missing_price(self, adapter):
        """Trade with no price returns no events."""
        adapter._token_to_condition = {"tok1": "cond1"}
        msg = {"event_type": "last_trade_price", "asset_id": "tok1"}
        assert adapter._normalize_ws_message(msg) == []


class TestSubscribe:
    async def test_subscribe_format(self, adapter):
        """Subscribe message has correct format."""
        sent = []

        class FakeWS:
            async def send(self, msg):
                sent.append(msg)

        await adapter._send_subscribe(FakeWS(), ["tok1", "tok2"])
        assert len(sent) == 1
        parsed = json.loads(sent[0])
        assert parsed["type"] == "market"
        assert parsed["assets_ids"] == ["tok1", "tok2"]
        assert parsed["custom_feature_enabled"] is True

    async def test_heartbeat_sends_ping(self, adapter):
        """Heartbeat loop sends PING strings."""
        sent = []

        class FakeWS:
            async def send(self, msg):
                sent.append(msg)
                if len(sent) >= 2:
                    raise asyncio.CancelledError()

        try:
            await adapter._heartbeat_loop(FakeWS())
        except asyncio.CancelledError:
            pass
        assert "PING" in sent
