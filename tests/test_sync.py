"""Tests for the data refresh layer (SyncLayer → BroadcastCache)."""

import time
from unittest.mock import AsyncMock

import pytest

from nexus.api.cache import BroadcastCache
from nexus.sync.sync import SyncLayer


NOW_MS = int(time.time() * 1000)


# ------------------------------------------------------------------
# Helpers
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


def _make_cache():
    return BroadcastCache()


# ------------------------------------------------------------------
# SyncLayer tests
# ------------------------------------------------------------------


class TestSyncMarkets:
    async def test_empty_market_state(self):
        store = _make_store()
        cache = _make_cache()
        layer = SyncLayer(store, cache)

        count = await layer.sync_markets()
        assert count == 0
        assert cache.get("markets") is None

    async def test_sync_markets_populates_cache(self):
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
        cache = _make_cache()
        layer = SyncLayer(store, cache)

        count = await layer.sync_markets()
        assert count == 1

        # Cache should have markets and stats
        entry = cache.get("markets")
        assert entry is not None
        assert len(entry.data) == 1
        assert entry.data[0]["platform"] == "kalshi"
        assert entry.data[0]["lastPrice"] == 0.65

        stats_entry = cache.get("market_stats")
        assert stats_entry is not None
        assert stats_entry.data["totalMarkets"] == 1
        assert stats_entry.data["activeMarkets"] == 1
        assert stats_entry.data["platformCounts"]["kalshi"] == 1


class TestSyncAnomalies:
    async def test_sync_anomalies_populates_cache(self):
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
        cache = _make_cache()
        layer = SyncLayer(store, cache)

        count = await layer.sync_anomalies()
        assert count == 1

        entry = cache.get("anomalies")
        assert entry is not None
        assert entry.data[0]["anomalyId"] == 42
        assert entry.data[0]["severity"] == 0.85

        stats_entry = cache.get("anomaly_stats")
        assert stats_entry is not None
        assert stats_entry.data["activeCount"] == 1
        assert stats_entry.data["bySeverityBucket"]["high"] == 1


class TestSyncTrendingTopics:
    async def test_empty_topics(self):
        store = _make_store()
        cache = _make_cache()
        layer = SyncLayer(store, cache)

        count = await layer.sync_trending_topics()
        assert count == 0

    async def test_sync_topics_populates_cache(self):
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
        cache = _make_cache()
        layer = SyncLayer(store, cache)

        count = await layer.sync_trending_topics()
        assert count == 1

        entry = cache.get("topics")
        assert entry is not None
        assert entry.data[0]["name"] == "US Politics"


class TestSyncMarketSummaries:
    async def test_sync_summaries_populates_cache(self):
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
        cache = _make_cache()
        layer = SyncLayer(store, cache)

        count = await layer.sync_market_summaries()
        assert count == 1

        entry = cache.get("summaries")
        assert entry is not None
        assert entry.data[0]["eventCount"] == 150


class TestSyncAll:
    async def test_sync_all_refreshes_views(self):
        store = _make_store()
        cache = _make_cache()
        layer = SyncLayer(store, cache)

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
        cache = _make_cache()
        layer = SyncLayer(store, cache)

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
        del store.refresh_views

        cache = _make_cache()
        layer = SyncLayer(store, cache)

        results = await layer.sync_all()
        assert results["markets"] == 0
