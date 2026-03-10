"""Tests for cross-platform correlation (Milestone 3.3)."""

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.core.types import (
    AnomalyMarketRecord,
    AnomalyRecord,
    AnomalyStatus,
    AnomalyType,
    CrossPlatformLink,
    MarketRecord,
    Platform,
    TopicCluster,
)
from nexus.correlation.cross_platform import CrossPlatformCorrelator


NOW_MS = int(time.time() * 1000)


def _market(mid: int, platform: str = "kalshi", title: str = "Test") -> MarketRecord:
    return MarketRecord(
        id=mid,
        platform=Platform(platform),
        external_id=f"ext-{mid}",
        title=title,
        first_seen_at=NOW_MS - 86400_000,
        last_updated_at=NOW_MS,
    )


def _anomaly(
    aid: int,
    severity: float = 0.5,
    summary: str = "price +10%",
) -> AnomalyRecord:
    return AnomalyRecord(
        id=aid,
        anomaly_type=AnomalyType.SINGLE_MARKET,
        severity=severity,
        market_count=1,
        window_start=NOW_MS - 3600_000,
        detected_at=NOW_MS - 1000,
        summary=summary,
        status=AnomalyStatus.ACTIVE,
    )


def _make_store():
    """Build a mock store with common defaults."""
    store = AsyncMock()
    store.get_clusters.return_value = []
    store.get_active_markets.return_value = []
    store.get_cross_platform_links.return_value = []
    store.get_anomalies.return_value = []
    store.upsert_cross_platform_link.return_value = 1
    store.insert_anomaly.return_value = 1
    return store


# ------------------------------------------------------------------
# build_links tests
# ------------------------------------------------------------------


class TestBuildLinks:
    async def test_no_clusters_returns_zero(self):
        store = _make_store()
        c = CrossPlatformCorrelator(store)
        assert await c.build_links() == 0

    async def test_single_platform_cluster_no_links(self):
        store = _make_store()
        store.get_clusters.return_value = [
            TopicCluster(id=1, name="Politics", created_at=NOW_MS, updated_at=NOW_MS)
        ]
        store.get_active_markets.return_value = [
            _market(10, "kalshi"),
            _market(11, "kalshi"),
        ]
        store.get_cluster_markets.return_value = [(10, 0.9), (11, 0.8)]

        c = CrossPlatformCorrelator(store)
        assert await c.build_links() == 0

    async def test_cross_platform_cluster_creates_links(self):
        store = _make_store()
        store.get_clusters.return_value = [
            TopicCluster(id=1, name="Politics", created_at=NOW_MS, updated_at=NOW_MS)
        ]
        store.get_active_markets.return_value = [
            _market(10, "kalshi"),
            _market(20, "polymarket"),
        ]
        store.get_cluster_markets.return_value = [(10, 0.9), (20, 0.8)]

        c = CrossPlatformCorrelator(store)
        count = await c.build_links()
        assert count == 1
        store.upsert_cross_platform_link.assert_called_once()
        link = store.upsert_cross_platform_link.call_args[0][0]
        assert link.confidence == 0.8  # min of 0.9, 0.8

    async def test_multiple_markets_per_platform_creates_all_pairs(self):
        store = _make_store()
        store.get_clusters.return_value = [
            TopicCluster(id=1, name="Sports", created_at=NOW_MS, updated_at=NOW_MS)
        ]
        store.get_active_markets.return_value = [
            _market(10, "kalshi"),
            _market(11, "kalshi"),
            _market(20, "polymarket"),
        ]
        store.get_cluster_markets.return_value = [(10, 0.9), (11, 0.8), (20, 0.7)]

        c = CrossPlatformCorrelator(store)
        count = await c.build_links()
        # kalshi(10) x polymarket(20), kalshi(11) x polymarket(20)
        assert count == 2


# ------------------------------------------------------------------
# correlate tests
# ------------------------------------------------------------------


class TestCorrelate:
    async def test_no_links_returns_empty(self):
        store = _make_store()
        c = CrossPlatformCorrelator(store)
        result = await c.correlate(NOW_MS)
        assert result == []

    async def test_no_anomalies_returns_empty(self):
        store = _make_store()
        store.get_cross_platform_links.return_value = [
            CrossPlatformLink(
                id=1, market_id_a=10, market_id_b=20,
                confidence=0.8, method="cluster", created_at=NOW_MS,
            )
        ]
        c = CrossPlatformCorrelator(store)
        result = await c.correlate(NOW_MS)
        assert result == []

    async def test_only_one_side_anomalous_returns_empty(self):
        store = _make_store()
        store.get_cross_platform_links.return_value = [
            CrossPlatformLink(
                id=1, market_id_a=10, market_id_b=20,
                confidence=0.8, method="cluster", created_at=NOW_MS,
            )
        ]
        anomaly = _anomaly(1)
        store.get_anomalies.side_effect = [
            [anomaly],  # recent single-market
            [],  # existing cross-platform (dedup)
        ]
        # Only market 10 has anomaly, not 20
        store.get_anomaly_markets.return_value = [
            AnomalyMarketRecord(anomaly_id=1, market_id=10)
        ]

        c = CrossPlatformCorrelator(store)
        result = await c.correlate(NOW_MS)
        assert result == []

    async def test_both_sides_anomalous_creates_cross_platform(self):
        store = _make_store()
        store.get_cross_platform_links.return_value = [
            CrossPlatformLink(
                id=1, market_id_a=10, market_id_b=20,
                confidence=0.8, method="cluster", created_at=NOW_MS,
            )
        ]
        a1 = _anomaly(1, severity=0.6, summary="price +5%")
        a2 = _anomaly(2, severity=0.7, summary="price +8%")
        store.get_anomalies.side_effect = [
            [a1, a2],  # recent single-market
            [],  # existing cross-platform (dedup)
        ]
        # a1 -> market 10, a2 -> market 20
        store.get_anomaly_markets.side_effect = [
            [AnomalyMarketRecord(anomaly_id=1, market_id=10)],
            [AnomalyMarketRecord(anomaly_id=2, market_id=20)],
        ]

        c = CrossPlatformCorrelator(store)
        result = await c.correlate(NOW_MS)
        assert len(result) == 1
        anomaly = result[0]
        assert anomaly.anomaly_type == AnomalyType.CROSS_PLATFORM
        assert anomaly.market_count == 2
        # Severity should be boosted: mean(0.6, 0.7) * 1.2 = 0.78
        assert anomaly.severity == pytest.approx(0.78, abs=0.01)

        meta = json.loads(anomaly.metadata)
        assert meta["signal_type"] == "convergent"
        assert meta["direction"] == "bullish"

    async def test_divergent_directions(self):
        store = _make_store()
        store.get_cross_platform_links.return_value = [
            CrossPlatformLink(
                id=1, market_id_a=10, market_id_b=20,
                confidence=0.9, method="cluster", created_at=NOW_MS,
            )
        ]
        a1 = _anomaly(1, severity=0.5, summary="price +10% spike")
        a2 = _anomaly(2, severity=0.5, summary="price -8% drop")
        store.get_anomalies.side_effect = [
            [a1, a2],
            [],
        ]
        store.get_anomaly_markets.side_effect = [
            [AnomalyMarketRecord(anomaly_id=1, market_id=10)],
            [AnomalyMarketRecord(anomaly_id=2, market_id=20)],
        ]

        c = CrossPlatformCorrelator(store)
        result = await c.correlate(NOW_MS)
        assert len(result) == 1
        meta = json.loads(result[0].metadata)
        assert meta["signal_type"] == "divergent"
        assert meta["direction"] == "mixed"

    async def test_dedup_existing_cross_platform(self):
        store = _make_store()
        store.get_cross_platform_links.return_value = [
            CrossPlatformLink(
                id=1, market_id_a=10, market_id_b=20,
                confidence=0.8, method="cluster", created_at=NOW_MS,
            )
        ]
        a1 = _anomaly(1, severity=0.6)
        a2 = _anomaly(2, severity=0.7)
        existing_xplat = AnomalyRecord(
            id=99,
            anomaly_type=AnomalyType.CROSS_PLATFORM,
            severity=0.7,
            market_count=2,
            window_start=NOW_MS - 3600_000,
            detected_at=NOW_MS - 500,
            metadata=json.dumps({"market_id_a": 10, "market_id_b": 20}),
        )
        store.get_anomalies.side_effect = [
            [a1, a2],  # recent single-market
            [existing_xplat],  # existing cross-platform
        ]
        store.get_anomaly_markets.side_effect = [
            [AnomalyMarketRecord(anomaly_id=1, market_id=10)],
            [AnomalyMarketRecord(anomaly_id=2, market_id=20)],
        ]

        c = CrossPlatformCorrelator(store)
        result = await c.correlate(NOW_MS)
        assert result == []

    async def test_correlate_and_store(self):
        store = _make_store()
        store.get_cross_platform_links.return_value = [
            CrossPlatformLink(
                id=1, market_id_a=10, market_id_b=20,
                confidence=0.8, method="cluster", created_at=NOW_MS,
            )
        ]
        a1 = _anomaly(1, severity=0.6, summary="price +5%")
        a2 = _anomaly(2, severity=0.7, summary="price +8%")
        store.get_anomalies.side_effect = [
            [a1, a2],
            [],
        ]
        store.get_anomaly_markets.side_effect = [
            [AnomalyMarketRecord(anomaly_id=1, market_id=10)],
            [AnomalyMarketRecord(anomaly_id=2, market_id=20)],
        ]

        c = CrossPlatformCorrelator(store)
        count = await c.correlate_and_store(NOW_MS)
        assert count == 1
        store.insert_anomaly.assert_called_once()
        anomaly_arg = store.insert_anomaly.call_args[0][0]
        links_arg = store.insert_anomaly.call_args[0][1]
        assert anomaly_arg.anomaly_type == AnomalyType.CROSS_PLATFORM
        assert len(links_arg) == 2  # both markets linked


# ------------------------------------------------------------------
# severity boost tests
# ------------------------------------------------------------------


class TestSeverityBoost:
    async def test_severity_capped_at_one(self):
        store = _make_store()
        store.get_cross_platform_links.return_value = [
            CrossPlatformLink(
                id=1, market_id_a=10, market_id_b=20,
                confidence=0.9, method="cluster", created_at=NOW_MS,
            )
        ]
        a1 = _anomaly(1, severity=0.95, summary="price +20%")
        a2 = _anomaly(2, severity=0.95, summary="price +15%")
        store.get_anomalies.side_effect = [[a1, a2], []]
        store.get_anomaly_markets.side_effect = [
            [AnomalyMarketRecord(anomaly_id=1, market_id=10)],
            [AnomalyMarketRecord(anomaly_id=2, market_id=20)],
        ]

        c = CrossPlatformCorrelator(store)
        result = await c.correlate(NOW_MS)
        assert len(result) == 1
        assert result[0].severity <= 1.0
