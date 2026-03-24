"""Tests for the REST API module (nexus.api)."""

import json

import pytest
from starlette.testclient import TestClient

from nexus.api.app import create_app
from nexus.api.cache import BroadcastCache


# -- Fixtures ----------------------------------------------------------------

SAMPLE_MARKETS = [
    {
        "marketId": 1,
        "platform": "kalshi",
        "externalId": "BTC-UP-100",
        "title": "Will Bitcoin exceed $100k?",
        "eventTitle": "Crypto prices",
        "category": "Crypto",
        "endDate": "2026-04-01",
        "isActive": True,
        "lastPrice": 0.65,
        "lastPriceTs": 1710900000000,
        "lastVolume": 10.0,
        "lastVolumeTs": 1710900000000,
        "volume": 500.0,
        "rankScore": 0.85,
        "healthScore": 0.72,
        "syncedAt": 1710900000000,
    },
    {
        "marketId": 2,
        "platform": "polymarket",
        "externalId": "pm-election-2026",
        "title": "2026 midterm outcome",
        "eventTitle": "US Elections",
        "category": "Politics",
        "endDate": "2026-11-03",
        "isActive": True,
        "lastPrice": 0.52,
        "lastPriceTs": 1710900000000,
        "lastVolume": None,
        "lastVolumeTs": None,
        "volume": 1200.0,
        "rankScore": 0.92,
        "healthScore": None,
        "syncedAt": 1710900000000,
    },
    {
        "marketId": 3,
        "platform": "kalshi",
        "externalId": "RAIN-NYC-0321",
        "title": "Rain in NYC on March 21?",
        "eventTitle": "Weather",
        "category": "Weather",
        "endDate": "2026-03-21",
        "isActive": False,
        "lastPrice": 0.30,
        "lastPriceTs": 1710800000000,
        "lastVolume": 5.0,
        "lastVolumeTs": 1710800000000,
        "volume": 50.0,
        "rankScore": 0.10,
        "healthScore": None,
        "syncedAt": 1710900000000,
    },
]

SAMPLE_ANOMALIES = [
    {
        "anomalyId": 10,
        "anomalyType": "price_spike",
        "severity": 0.85,
        "marketCount": 1,
        "detectedAt": 1710900000000,
        "summary": "BTC-UP-100 +5.2% in 15min",
        "metadata": "{}",
        "clusterName": "Crypto",
        "catalyst": {
            "headline": "Large trades drove BTC-UP-100 surged 5.2%",
            "narrative": "BTC surged on whale activity.",
            "catalyst_type": "whale",
            "confidence": 0.65,
            "signals": ["62% whale volume", "5 trades"],
            "source": "template",
        },
        "syncedAt": 1710900000000,
    },
    {
        "anomalyId": 11,
        "anomalyType": "cluster",
        "severity": 0.45,
        "marketCount": 3,
        "detectedAt": 1710899000000,
        "summary": "Politics cluster activity",
        "metadata": "{}",
        "clusterName": "US Politics",
        "catalyst": None,
        "syncedAt": 1710900000000,
    },
]

SAMPLE_TOPICS = [
    {
        "clusterId": 1,
        "name": "Crypto Markets",
        "description": "Bitcoin and altcoin prediction markets",
        "marketCount": 15,
        "anomalyCount": 3,
        "maxSeverity": 0.85,
        "syncedAt": 1710900000000,
    },
    {
        "clusterId": 2,
        "name": "US Politics",
        "description": "Election and policy markets",
        "marketCount": 30,
        "anomalyCount": 1,
        "maxSeverity": 0.45,
        "syncedAt": 1710900000000,
    },
]


@pytest.fixture
def populated_cache() -> BroadcastCache:
    cache = BroadcastCache()
    cache.update("markets", SAMPLE_MARKETS, max_age=30)
    cache.update(
        "market_stats",
        BroadcastCache.compute_market_stats(SAMPLE_MARKETS),
        max_age=30,
    )
    cache.update("anomalies", SAMPLE_ANOMALIES, max_age=30)
    cache.update(
        "anomaly_stats",
        BroadcastCache.compute_anomaly_stats(SAMPLE_ANOMALIES),
        max_age=30,
    )
    cache.update("topics", SAMPLE_TOPICS, max_age=120)
    return cache


@pytest.fixture
def client(populated_cache: BroadcastCache) -> TestClient:
    app = create_app(cache=populated_cache)
    return TestClient(app)


@pytest.fixture
def empty_client() -> TestClient:
    app = create_app(cache=BroadcastCache())
    return TestClient(app)


# -- Cache unit tests --------------------------------------------------------


class TestBroadcastCache:
    def test_update_and_get(self) -> None:
        cache = BroadcastCache()
        cache.update("test", [1, 2, 3], max_age=60)
        entry = cache.get("test")
        assert entry is not None
        assert entry.data == [1, 2, 3]
        assert entry.max_age == 60
        assert entry.etag
        assert entry.json_bytes == b"[1,2,3]"

    def test_get_missing_key(self) -> None:
        cache = BroadcastCache()
        assert cache.get("nonexistent") is None

    def test_etag_changes_on_update(self) -> None:
        cache = BroadcastCache()
        cache.update("k", {"a": 1})
        etag1 = cache.get("k").etag
        cache.update("k", {"a": 2})
        etag2 = cache.get("k").etag
        assert etag1 != etag2

    def test_compute_market_stats(self) -> None:
        stats = BroadcastCache.compute_market_stats(SAMPLE_MARKETS)
        assert stats["totalMarkets"] == 3
        assert stats["activeMarkets"] == 2
        assert stats["platformCounts"]["kalshi"] == 2
        assert stats["platformCounts"]["polymarket"] == 1
        assert stats["categoryCounts"]["Crypto"] == 1

    def test_compute_anomaly_stats(self) -> None:
        stats = BroadcastCache.compute_anomaly_stats(SAMPLE_ANOMALIES)
        assert stats["activeCount"] == 2
        assert stats["bySeverityBucket"]["high"] == 1
        assert stats["bySeverityBucket"]["medium"] == 1
        assert stats["bySeverityBucket"]["low"] == 0

    def test_compute_anomaly_stats_empty(self) -> None:
        stats = BroadcastCache.compute_anomaly_stats([])
        assert stats["activeCount"] == 0
        assert stats["avgSeverity"] == 0

    def test_get_status(self) -> None:
        cache = BroadcastCache()
        cache.update("markets", [1, 2], max_age=30)
        status = cache.get_status()
        assert "markets" in status
        assert status["markets"]["recordCount"] == 2
        assert status["markets"]["lastRefresh"] > 0


# -- Endpoint tests ----------------------------------------------------------


class TestMarketsEndpoint:
    def test_get_markets(self, client: TestClient) -> None:
        resp = client.get("/api/v1/markets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["markets"]) == 3

    def test_filter_by_platform(self, client: TestClient) -> None:
        resp = client.get("/api/v1/markets?platform=kalshi")
        data = resp.json()
        assert data["total"] == 2
        assert all(m["platform"] == "kalshi" for m in data["markets"])

    def test_search(self, client: TestClient) -> None:
        resp = client.get("/api/v1/markets?search=bitcoin")
        data = resp.json()
        assert data["total"] == 1
        assert data["markets"][0]["externalId"] == "BTC-UP-100"

    def test_pagination(self, client: TestClient) -> None:
        resp = client.get("/api/v1/markets?limit=1&offset=1")
        data = resp.json()
        assert len(data["markets"]) == 1
        assert data["total"] == 3
        assert data["offset"] == 1

    def test_sort_by_rank(self, client: TestClient) -> None:
        resp = client.get("/api/v1/markets?sort=rank_score")
        data = resp.json()
        scores = [m["rankScore"] for m in data["markets"]]
        assert scores == sorted(scores, reverse=True)

    def test_empty_cache(self, empty_client: TestClient) -> None:
        resp = empty_client.get("/api/v1/markets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    def test_cache_headers(self, client: TestClient) -> None:
        resp = client.get("/api/v1/markets")
        assert "Cache-Control" in resp.headers
        assert "max-age=" in resp.headers["Cache-Control"]


class TestMarketStatsEndpoint:
    def test_get_stats(self, client: TestClient) -> None:
        resp = client.get("/api/v1/markets/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totalMarkets"] == 3
        assert data["activeMarkets"] == 2

    def test_etag_conditional(self, client: TestClient) -> None:
        resp1 = client.get("/api/v1/markets/stats")
        etag = resp1.headers.get("ETag", "").strip('"')
        resp2 = client.get(
            "/api/v1/markets/stats", headers={"If-None-Match": f'"{etag}"'}
        )
        assert resp2.status_code == 304


class TestAnomaliesEndpoint:
    def test_get_anomalies(self, client: TestClient) -> None:
        resp = client.get("/api/v1/anomalies")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_filter_by_type(self, client: TestClient) -> None:
        resp = client.get("/api/v1/anomalies?anomaly_type=cluster")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["anomalyType"] == "cluster"

    def test_filter_by_severity(self, client: TestClient) -> None:
        resp = client.get("/api/v1/anomalies?min_severity=0.7")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["severity"] >= 0.7

    def test_limit(self, client: TestClient) -> None:
        resp = client.get("/api/v1/anomalies?limit=1")
        data = resp.json()
        assert len(data) == 1


class TestAnomalyStatsEndpoint:
    def test_get_stats(self, client: TestClient) -> None:
        resp = client.get("/api/v1/anomalies/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["activeCount"] == 2
        assert "bySeverityBucket" in data


class TestTopicsEndpoint:
    def test_get_topics(self, client: TestClient) -> None:
        resp = client.get("/api/v1/topics")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_limit(self, client: TestClient) -> None:
        resp = client.get("/api/v1/topics?limit=1")
        data = resp.json()
        assert len(data) == 1


class TestStatusEndpoint:
    def test_get_status(self, client: TestClient) -> None:
        resp = client.get("/api/v1/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "markets" in data
        assert "anomalies" in data

    def test_empty_cache_status(self, empty_client: TestClient) -> None:
        resp = empty_client.get("/api/v1/status")
        assert resp.status_code == 200
        assert resp.json() == {}


class TestCandlesticksEndpoint:
    def test_no_data(self, client: TestClient) -> None:
        """Without a store or adapter, returns empty list."""
        resp = client.get("/api/v1/candlesticks/NONEXISTENT")
        assert resp.status_code == 200
        assert resp.json() == []


class TestCORS:
    def test_cors_headers(self, client: TestClient) -> None:
        resp = client.options(
            "/api/v1/markets",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
        )
        assert resp.headers.get("access-control-allow-origin") == "*"
