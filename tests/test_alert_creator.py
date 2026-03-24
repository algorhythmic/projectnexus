"""Tests for the AlertCreator pipeline (Milestone 5.2)."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.alerts.creator import AlertCreator


@pytest.fixture
def mock_convex():
    client = AsyncMock()
    # Default: return list of alertable users
    client.query = AsyncMock(return_value=[
        {"userId": "user1", "categories": [], "platforms": []},
        {"userId": "user2", "categories": ["Crypto"], "platforms": ["kalshi"]},
    ])
    # Default: batch creation returns count
    client.mutation = AsyncMock(return_value=1)
    return client


@pytest.fixture
def creator(mock_convex):
    return AlertCreator(mock_convex, max_alerts_per_user_per_hour=5)


def _make_anomaly(
    anomaly_id: int,
    severity: float = 0.5,
    cluster_name: str = "Crypto",
    catalyst: dict = None,
) -> dict:
    return {
        "anomalyId": anomaly_id,
        "anomalyType": "single_market",
        "severity": severity,
        "marketCount": 1,
        "detectedAt": int(time.time() * 1000),
        "summary": f"Test anomaly {anomaly_id}",
        "metadata": "",
        "clusterName": cluster_name,
        "catalyst": catalyst,
        "syncedAt": int(time.time() * 1000),
    }


class TestPreferenceMatching:
    def test_empty_prefs_matches_all(self):
        user = {"userId": "u1", "categories": [], "platforms": []}
        assert AlertCreator._matches_preferences(user, category="Crypto") is True
        assert AlertCreator._matches_preferences(user, platform="kalshi") is True

    def test_category_filter_matches(self):
        user = {"userId": "u1", "categories": ["Crypto", "Politics"], "platforms": []}
        assert AlertCreator._matches_preferences(user, category="Crypto") is True
        assert AlertCreator._matches_preferences(user, category="Sports") is False

    def test_category_case_insensitive(self):
        user = {"userId": "u1", "categories": ["crypto"], "platforms": []}
        assert AlertCreator._matches_preferences(user, category="Crypto") is True

    def test_platform_filter_matches(self):
        user = {"userId": "u1", "categories": [], "platforms": ["kalshi"]}
        assert AlertCreator._matches_preferences(user, platform="kalshi") is True
        assert AlertCreator._matches_preferences(user, platform="polymarket") is False

    def test_both_filters(self):
        user = {"userId": "u1", "categories": ["Crypto"], "platforms": ["kalshi"]}
        assert AlertCreator._matches_preferences(
            user, category="Crypto", platform="kalshi"
        ) is True
        assert AlertCreator._matches_preferences(
            user, category="Sports", platform="kalshi"
        ) is False

    def test_empty_category_skips_filter(self):
        user = {"userId": "u1", "categories": ["Crypto"], "platforms": []}
        # No category on the anomaly — should pass through
        assert AlertCreator._matches_preferences(user, category="") is True


class TestDeduplication:
    async def test_same_anomaly_not_alerted_twice(self, creator, mock_convex):
        anomaly = _make_anomaly(100)
        await creator.process_new_anomalies([anomaly])
        await creator.process_new_anomalies([anomaly])
        # Should only call mutation once (first time)
        assert mock_convex.mutation.call_count == 1

    async def test_different_anomalies_both_alerted(self, creator, mock_convex):
        a1 = _make_anomaly(100)
        a2 = _make_anomaly(101)
        await creator.process_new_anomalies([a1])
        await creator.process_new_anomalies([a2])
        assert mock_convex.mutation.call_count == 2


class TestThrottling:
    async def test_throttle_per_user(self, creator, mock_convex):
        # Set low limit
        creator._max_per_hour = 2
        # Only user1 (no filters) should match — create 3 anomalies
        mock_convex.query = AsyncMock(return_value=[
            {"userId": "user1", "categories": [], "platforms": []},
        ])
        anomalies = [_make_anomaly(i) for i in range(5)]
        await creator.process_new_anomalies(anomalies)
        # Should only create 2 alerts (throttled at 2/hour)
        call_args = mock_convex.mutation.call_args
        alerts_sent = call_args[1]["args"]["alerts"] if "args" in call_args[1] else call_args[0][1]["alerts"]
        assert len(alerts_sent) == 2


class TestAlertCreation:
    async def test_creates_alerts_for_matching_users(self, creator, mock_convex):
        anomaly = _make_anomaly(200, cluster_name="Crypto")
        count = await creator.process_new_anomalies([anomaly])
        assert count >= 1
        mock_convex.mutation.assert_called_once()

    async def test_no_alerts_when_no_users(self, creator, mock_convex):
        mock_convex.query = AsyncMock(return_value=[])
        anomaly = _make_anomaly(300)
        count = await creator.process_new_anomalies([anomaly])
        assert count == 0
        mock_convex.mutation.assert_not_called()

    async def test_no_alerts_for_empty_list(self, creator, mock_convex):
        count = await creator.process_new_anomalies([])
        assert count == 0
        mock_convex.mutation.assert_not_called()

    async def test_uses_catalyst_headline_when_available(self, creator, mock_convex):
        catalyst = {
            "headline": "Whale surge on BTC",
            "narrative": "...",
            "catalyst_type": "whale",
            "confidence": 0.6,
            "signals": [],
            "source": "template",
        }
        anomaly = _make_anomaly(400, catalyst=catalyst)
        await creator.process_new_anomalies([anomaly])
        call_args = mock_convex.mutation.call_args
        alerts = call_args[0][1]["alerts"] if len(call_args[0]) > 1 else call_args[1]["args"]["alerts"]
        assert any("Whale surge" in a["title"] for a in alerts)

    async def test_convex_error_handled_gracefully(self, creator, mock_convex):
        from nexus.sync.convex_client import ConvexError
        mock_convex.mutation = AsyncMock(side_effect=ConvexError("test"))
        anomaly = _make_anomaly(500)
        count = await creator.process_new_anomalies([anomaly])
        assert count == 0  # Graceful failure

    async def test_user_cache_reused(self, creator, mock_convex):
        a1 = _make_anomaly(600)
        a2 = _make_anomaly(601)
        await creator.process_new_anomalies([a1])
        await creator.process_new_anomalies([a2])
        # Query should only be called once (cached for 5 min)
        assert mock_convex.query.call_count == 1
