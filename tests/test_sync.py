"""Tests for the Convex sync layer (Phase 4, Milestone 4.1)."""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.sync.convex_client import ConvexClient, ConvexError
from nexus.sync.sync import SyncLayer


NOW_MS = int(time.time() * 1000)


# ------------------------------------------------------------------
# ConvexClient tests
# ------------------------------------------------------------------


class TestConvexClient:
    async def test_mutation_success(self):
        client = ConvexClient("https://test.convex.cloud", "test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"status": "success", "value": {"upserted": 5}}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            result = await client.mutation("nexusSync:upsertMarkets", {"markets": []})
            assert result == {"upserted": 5}

        await client.close()

    async def test_mutation_convex_error(self):
        client = ConvexClient("https://test.convex.cloud", "test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "status": "error",
            "errorMessage": "Validation failed",
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(ConvexError, match="rejected"):
                await client.mutation("nexusSync:bad", {"x": 1})

        await client.close()

    async def test_query_success(self):
        client = ConvexClient("https://test.convex.cloud", "test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"status": "success", "value": [{"id": 1}]}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            result = await client.query("etl:getMarketStats")
            assert result == [{"id": 1}]

        await client.close()

    async def test_close_idempotent(self):
        client = ConvexClient("https://test.convex.cloud", "test-key")
        await client.close()  # no client created yet
        await client.close()  # still safe


# ------------------------------------------------------------------
# SyncLayer tests
# ------------------------------------------------------------------


def _make_store():
    """Build a mock PostgresStore with view query methods."""
    store = AsyncMock()
    store.query_market_state.return_value = []
    store.query_active_anomalies.return_value = []
    store.query_trending_topics.return_value = []
    store.query_market_summaries.return_value = []
    store.refresh_views = AsyncMock()
    return store


def _make_convex():
    """Build a mock ConvexClient."""
    convex = AsyncMock(spec=ConvexClient)
    convex.mutation.return_value = {"upserted": 0}
    return convex


class TestSyncMarkets:
    async def test_empty_market_state(self):
        store = _make_store()
        convex = _make_convex()
        layer = SyncLayer(store, convex)

        count = await layer.sync_markets()
        assert count == 0
        convex.mutation.assert_not_called()

    async def test_sync_markets_calls_mutation(self):
        store = _make_store()
        store.query_market_state.return_value = [
            {
                "market_id": 1,
                "platform": "kalshi",
                "external_id": "ext-1",
                "title": "Will X happen?",
                "category": "politics",
                "is_active": True,
                "last_price": 0.65,
                "last_price_ts": NOW_MS - 1000,
                "last_volume": 5000.0,
                "last_volume_ts": NOW_MS - 2000,
            },
        ]
        convex = _make_convex()
        layer = SyncLayer(store, convex)

        count = await layer.sync_markets()
        assert count == 1
        # Two mutations: upsert + cleanup
        assert convex.mutation.call_count == 2
        upsert_call = convex.mutation.call_args_list[0]
        assert upsert_call[0][0] == "nexusSync:upsertMarkets"
        markets = upsert_call[0][1]["markets"]
        assert len(markets) == 1
        assert markets[0]["platform"] == "kalshi"
        assert markets[0]["lastPrice"] == 0.65
        cleanup_call = convex.mutation.call_args_list[1]
        assert cleanup_call[0][0] == "nexusSync:cleanupStaleMarkets"


class TestSyncAnomalies:
    async def test_sync_anomalies_calls_mutation(self):
        store = _make_store()
        store.query_active_anomalies.return_value = [
            {
                "anomaly_id": 42,
                "anomaly_type": "cluster",
                "severity": 0.85,
                "market_count": 3,
                "detected_at": NOW_MS - 5000,
                "summary": "Politics cluster anomaly",
                "metadata": '{"direction": "bullish"}',
                "cluster_name": "US Politics",
            },
        ]
        convex = _make_convex()
        layer = SyncLayer(store, convex)

        count = await layer.sync_anomalies()
        assert count == 1
        call_args = convex.mutation.call_args
        assert call_args[0][0] == "nexusSync:upsertAnomalies"
        anomalies = call_args[0][1]["anomalies"]
        assert anomalies[0]["anomalyId"] == 42
        assert anomalies[0]["severity"] == 0.85


class TestSyncTrendingTopics:
    async def test_empty_topics(self):
        store = _make_store()
        convex = _make_convex()
        layer = SyncLayer(store, convex)

        count = await layer.sync_trending_topics()
        assert count == 0

    async def test_sync_topics_calls_mutation(self):
        store = _make_store()
        store.query_trending_topics.return_value = [
            {
                "cluster_id": 1,
                "name": "US Politics",
                "description": "Political events",
                "market_count": 10,
                "anomaly_count": 3,
                "max_severity": 0.9,
            },
        ]
        convex = _make_convex()
        layer = SyncLayer(store, convex)

        count = await layer.sync_trending_topics()
        assert count == 1
        call_args = convex.mutation.call_args
        assert call_args[0][0] == "nexusSync:upsertTrendingTopics"


class TestSyncMarketSummaries:
    async def test_sync_summaries_calls_mutation(self):
        store = _make_store()
        store.query_market_summaries.return_value = [
            {
                "market_id": 1,
                "platform": "kalshi",
                "title": "Will X happen?",
                "category": "politics",
                "event_count": 150,
                "first_event_ts": NOW_MS - 86400_000,
                "last_event_ts": NOW_MS - 1000,
            },
        ]
        convex = _make_convex()
        layer = SyncLayer(store, convex)

        count = await layer.sync_market_summaries()
        assert count == 1


class TestSyncAll:
    async def test_sync_all_refreshes_views(self):
        store = _make_store()
        convex = _make_convex()
        layer = SyncLayer(store, convex)

        results = await layer.sync_all()
        store.refresh_views.assert_called_once()
        assert results == {
            "markets": 0,
            "anomalies": 0,
            "trending_topics": 0,
            "market_summaries": 0,
        }

    async def test_sync_all_returns_counts(self):
        store = _make_store()
        store.query_market_state.return_value = [
            {
                "market_id": 1, "platform": "kalshi", "external_id": "x",
                "title": "T", "category": "C", "is_active": True,
                "last_price": 0.5, "last_price_ts": NOW_MS,
                "last_volume": None, "last_volume_ts": None,
            },
        ]
        store.query_active_anomalies.return_value = [
            {
                "anomaly_id": 1, "anomaly_type": "single_market",
                "severity": 0.7, "market_count": 1, "detected_at": NOW_MS,
                "summary": "x", "metadata": "", "cluster_name": "",
            },
            {
                "anomaly_id": 2, "anomaly_type": "cluster",
                "severity": 0.8, "market_count": 2, "detected_at": NOW_MS,
                "summary": "y", "metadata": "", "cluster_name": "Z",
            },
        ]
        convex = _make_convex()
        layer = SyncLayer(store, convex)

        results = await layer.sync_all()
        assert results["markets"] == 1
        assert results["anomalies"] == 2
        assert results["trending_topics"] == 0
        assert results["market_summaries"] == 0

    async def test_sync_all_without_refresh_views(self):
        """Works with stores that don't have refresh_views (SQLite)."""
        store = AsyncMock()
        store.query_market_state.return_value = []
        store.query_active_anomalies.return_value = []
        store.query_trending_topics.return_value = []
        store.query_market_summaries.return_value = []
        # Intentionally no refresh_views attribute
        del store.refresh_views

        convex = _make_convex()
        layer = SyncLayer(store, convex)

        results = await layer.sync_all()
        assert results["markets"] == 0
