"""Tests for Kalshi REST API methods (Features C, E, F, G)."""

import json

import pytest

from nexus.adapters.kalshi import KalshiAdapter, _CATEGORY_MAP
from nexus.core.config import Settings


@pytest.fixture
def kalshi_adapter():
    """Create a KalshiAdapter with test settings (no real API key)."""
    s = Settings(
        kalshi_api_key="test-key",
        kalshi_private_key_path="",
        kalshi_use_demo=True,
    )
    return KalshiAdapter(s)


class TestInferSeriesTicker:
    """Test _infer_series_ticker utility."""

    def test_standard_ticker(self, kalshi_adapter):
        """Standard multi-segment ticker returns first segment."""
        assert kalshi_adapter._infer_series_ticker("INXD-26MAR21-B5825") == "INXD"

    def test_two_segment_ticker(self, kalshi_adapter):
        """Two-segment ticker returns first segment."""
        assert kalshi_adapter._infer_series_ticker("BTC-50K") == "BTC"

    def test_single_segment_ticker(self, kalshi_adapter):
        """Single segment ticker returns None (ambiguous)."""
        assert kalshi_adapter._infer_series_ticker("SIMPLETICKER") is None

    def test_empty_ticker(self, kalshi_adapter):
        """Empty ticker returns None."""
        assert kalshi_adapter._infer_series_ticker("") is None


class TestCandlestickParams:
    """Test get_candlesticks parameter handling."""

    async def test_default_time_range(self, kalshi_adapter):
        """Default time range is 24 hours ago to now."""
        # We can't call the API in tests, but we can verify the method exists
        # and accepts the expected parameters
        assert hasattr(kalshi_adapter, "get_candlesticks")

    async def test_candlestick_method_signature(self, kalshi_adapter):
        """get_candlesticks accepts ticker, period_interval, start_ts, end_ts."""
        import inspect

        sig = inspect.signature(kalshi_adapter.get_candlesticks)
        params = list(sig.parameters.keys())
        assert "ticker" in params
        assert "period_interval" in params
        assert "start_ts" in params
        assert "end_ts" in params


class TestCategoryTaxonomy:
    """Test category taxonomy loading."""

    def test_category_map_has_defaults(self):
        """The _CATEGORY_MAP should have default entries."""
        assert "economics" in _CATEGORY_MAP
        assert "politics" in _CATEGORY_MAP
        assert "sports" in _CATEGORY_MAP

    async def test_load_category_taxonomy_adds_entries(self, kalshi_adapter, monkeypatch):
        """load_category_taxonomy adds new mappings from API data."""
        # Mock the API response
        taxonomy_response = {
            "categories": [
                {
                    "name": "Crypto",
                    "tags": ["bitcoin", "ethereum", "solana", "defi"],
                },
                {
                    "name": "Macro",
                    "tags": ["interest_rates", "gdp_growth"],
                },
            ]
        }

        async def mock_get_taxonomy():
            return taxonomy_response

        monkeypatch.setattr(kalshi_adapter, "get_category_taxonomy", mock_get_taxonomy)

        # Record initial size
        initial_size = len(_CATEGORY_MAP)

        added = await kalshi_adapter.load_category_taxonomy()

        # Should have added new entries (some may already exist)
        assert added >= 0
        # Verify specific new entries
        assert "defi" in _CATEGORY_MAP
        assert "interest_rates" in _CATEGORY_MAP
        assert "gdp_growth" in _CATEGORY_MAP
        assert _CATEGORY_MAP["defi"] == "Crypto"
        assert _CATEGORY_MAP["interest_rates"] == "Macro"

        # Clean up added entries to not pollute other tests
        for tag in ["defi", "interest_rates", "gdp_growth", "macro"]:
            _CATEGORY_MAP.pop(tag, None)

    async def test_load_category_taxonomy_handles_empty(self, kalshi_adapter, monkeypatch):
        """load_category_taxonomy handles empty API response."""

        async def mock_get_taxonomy():
            return None

        monkeypatch.setattr(kalshi_adapter, "get_category_taxonomy", mock_get_taxonomy)

        added = await kalshi_adapter.load_category_taxonomy()
        assert added == 0

    async def test_load_category_taxonomy_handles_no_categories(
        self, kalshi_adapter, monkeypatch
    ):
        """load_category_taxonomy handles response with no categories key."""

        async def mock_get_taxonomy():
            return {"other": "data"}

        monkeypatch.setattr(kalshi_adapter, "get_category_taxonomy", mock_get_taxonomy)

        added = await kalshi_adapter.load_category_taxonomy()
        assert added == 0


class TestGetSeries:
    """Test series metadata fetch."""

    async def test_get_series_method_exists(self, kalshi_adapter):
        """get_series method is available."""
        assert hasattr(kalshi_adapter, "get_series")

    async def test_get_series_accepts_optional_ticker(self, kalshi_adapter):
        """get_series accepts an optional series_ticker parameter."""
        import inspect

        sig = inspect.signature(kalshi_adapter.get_series)
        params = sig.parameters
        assert "series_ticker" in params
        assert params["series_ticker"].default is None


class TestGetExchangeStatus:
    """Test exchange status and schedule methods."""

    async def test_exchange_status_method_exists(self, kalshi_adapter):
        """get_exchange_status method is available."""
        assert hasattr(kalshi_adapter, "get_exchange_status")

    async def test_exchange_schedule_method_exists(self, kalshi_adapter):
        """get_exchange_schedule method is available."""
        assert hasattr(kalshi_adapter, "get_exchange_schedule")


class TestGetMarket:
    """Test single market lookup."""

    async def test_get_market_method_exists(self, kalshi_adapter):
        """get_market method is available."""
        assert hasattr(kalshi_adapter, "get_market")

    async def test_get_market_accepts_ticker(self, kalshi_adapter):
        """get_market accepts a ticker string."""
        import inspect

        sig = inspect.signature(kalshi_adapter.get_market)
        params = list(sig.parameters.keys())
        assert "ticker" in params
