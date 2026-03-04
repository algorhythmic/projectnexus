"""Tests for ClusterCorrelator."""

import json
import time

import pytest

from nexus.core.types import (
    AnomalyMarketRecord,
    AnomalyRecord,
    AnomalyStatus,
    AnomalyType,
    DiscoveredMarket,
    Platform,
    TopicCluster,
)
from nexus.correlation.correlator import ClusterCorrelator


async def _insert_market(store, external_id: str) -> int:
    """Insert a test market and return its id."""
    market = DiscoveredMarket(
        platform=Platform.KALSHI,
        external_id=external_id,
        title=f"Corr Test {external_id}",
        yes_price=0.5,
    )
    await store.upsert_markets([market])
    stored = await store.get_market_by_external_id("kalshi", external_id)
    return stored.id


async def _create_cluster(store, name: str, market_ids: list[int]) -> int:
    """Create a cluster and assign markets to it."""
    now = int(time.time() * 1000)
    cid = await store.insert_cluster(TopicCluster(
        name=name, description=f"{name} cluster",
        created_at=now, updated_at=now,
    ))
    for mid in market_ids:
        await store.assign_market_to_cluster(mid, cid, 0.9)
    return cid


async def _insert_anomaly(
    store, market_id: int, detected_at: int,
    severity: float = 0.7, summary: str = "test anomaly",
) -> int:
    """Insert a SINGLE_MARKET anomaly for a market."""
    anomaly = AnomalyRecord(
        anomaly_type=AnomalyType.SINGLE_MARKET,
        severity=severity,
        market_count=1,
        window_start=detected_at - 300_000,
        detected_at=detected_at,
        summary=summary,
    )
    links = [AnomalyMarketRecord(
        anomaly_id=0, market_id=market_id,
        price_delta=0.05, volume_ratio=2.0,
    )]
    return await store.insert_anomaly(anomaly, links)


class TestClusterCorrelator:
    async def test_no_clusters_returns_empty(self, tmp_store):
        """No clusters in store returns empty list."""
        correlator = ClusterCorrelator(tmp_store, min_cluster_markets=2)
        result = await correlator.correlate(now_ms=1_000_000)
        assert result == []

    async def test_no_anomalies_returns_empty(self, tmp_store):
        """Clusters exist but no anomalies returns empty."""
        mid = await _insert_market(tmp_store, "CORR-1")
        await _create_cluster(tmp_store, "Finance", [mid])

        correlator = ClusterCorrelator(tmp_store, min_cluster_markets=2)
        result = await correlator.correlate(now_ms=1_000_000)
        assert result == []

    async def test_single_anomaly_below_threshold(self, tmp_store):
        """One market anomalous, min=2 → no cluster anomaly."""
        mid1 = await _insert_market(tmp_store, "CORR-A1")
        mid2 = await _insert_market(tmp_store, "CORR-A2")
        await _create_cluster(tmp_store, "Tech", [mid1, mid2])

        now = 1_000_000
        await _insert_anomaly(tmp_store, mid1, now - 60_000)

        correlator = ClusterCorrelator(
            tmp_store, min_cluster_markets=2, cluster_window_minutes=60
        )
        result = await correlator.correlate(now_ms=now)
        assert result == []

    async def test_cluster_anomaly_fires(self, tmp_store):
        """Two markets anomalous, min=2 → cluster anomaly fires."""
        mid1 = await _insert_market(tmp_store, "CORR-B1")
        mid2 = await _insert_market(tmp_store, "CORR-B2")
        cid = await _create_cluster(tmp_store, "Finance", [mid1, mid2])

        now = 1_000_000
        await _insert_anomaly(tmp_store, mid1, now - 60_000)
        await _insert_anomaly(tmp_store, mid2, now - 30_000)

        correlator = ClusterCorrelator(
            tmp_store, min_cluster_markets=2, cluster_window_minutes=60
        )
        result = await correlator.correlate(now_ms=now)

        assert len(result) == 1
        anomaly = result[0]
        assert anomaly.anomaly_type == AnomalyType.CLUSTER
        assert anomaly.topic_cluster_id == cid
        assert anomaly.market_count == 2

    async def test_cluster_anomaly_severity_aggregation(self, tmp_store):
        """Severity = mean of per-market max severities."""
        mid1 = await _insert_market(tmp_store, "CORR-C1")
        mid2 = await _insert_market(tmp_store, "CORR-C2")
        await _create_cluster(tmp_store, "Energy", [mid1, mid2])

        now = 1_000_000
        await _insert_anomaly(tmp_store, mid1, now - 60_000, severity=0.8)
        await _insert_anomaly(tmp_store, mid2, now - 30_000, severity=0.6)

        correlator = ClusterCorrelator(
            tmp_store, min_cluster_markets=2, cluster_window_minutes=60
        )
        result = await correlator.correlate(now_ms=now)

        assert len(result) == 1
        # mean(0.8, 0.6) = 0.7
        assert result[0].severity == pytest.approx(0.7, abs=0.01)

    async def test_direction_bullish(self, tmp_store):
        """All positive price summaries → bullish."""
        mid1 = await _insert_market(tmp_store, "CORR-D1")
        mid2 = await _insert_market(tmp_store, "CORR-D2")
        await _create_cluster(tmp_store, "Bull", [mid1, mid2])

        now = 1_000_000
        await _insert_anomaly(
            tmp_store, mid1, now - 60_000,
            summary="market_id=1: +15.0% price in 5min window",
        )
        await _insert_anomaly(
            tmp_store, mid2, now - 30_000,
            summary="market_id=2: +10.0% price in 5min window",
        )

        correlator = ClusterCorrelator(
            tmp_store, min_cluster_markets=2, cluster_window_minutes=60
        )
        result = await correlator.correlate(now_ms=now)

        assert len(result) == 1
        meta = json.loads(result[0].metadata)
        assert meta["direction"] == "bullish"

    async def test_direction_bearish(self, tmp_store):
        """All negative price summaries → bearish."""
        mid1 = await _insert_market(tmp_store, "CORR-E1")
        mid2 = await _insert_market(tmp_store, "CORR-E2")
        await _create_cluster(tmp_store, "Bear", [mid1, mid2])

        now = 1_000_000
        await _insert_anomaly(
            tmp_store, mid1, now - 60_000,
            summary="market_id=1: -12.0% price in 5min window",
        )
        await _insert_anomaly(
            tmp_store, mid2, now - 30_000,
            summary="market_id=2: -8.0% price in 5min window",
        )

        correlator = ClusterCorrelator(
            tmp_store, min_cluster_markets=2, cluster_window_minutes=60
        )
        result = await correlator.correlate(now_ms=now)

        assert len(result) == 1
        meta = json.loads(result[0].metadata)
        assert meta["direction"] == "bearish"

    async def test_direction_mixed(self, tmp_store):
        """Mix of +/- price summaries → mixed."""
        mid1 = await _insert_market(tmp_store, "CORR-F1")
        mid2 = await _insert_market(tmp_store, "CORR-F2")
        await _create_cluster(tmp_store, "Mixed", [mid1, mid2])

        now = 1_000_000
        await _insert_anomaly(
            tmp_store, mid1, now - 60_000,
            summary="market_id=1: +15.0% price in 5min window",
        )
        await _insert_anomaly(
            tmp_store, mid2, now - 30_000,
            summary="market_id=2: -10.0% price in 5min window",
        )

        correlator = ClusterCorrelator(
            tmp_store, min_cluster_markets=2, cluster_window_minutes=60
        )
        result = await correlator.correlate(now_ms=now)

        assert len(result) == 1
        meta = json.loads(result[0].metadata)
        assert meta["direction"] == "mixed"

    async def test_outside_window_ignored(self, tmp_store):
        """Anomalies older than the window are not counted."""
        mid1 = await _insert_market(tmp_store, "CORR-G1")
        mid2 = await _insert_market(tmp_store, "CORR-G2")
        await _create_cluster(tmp_store, "Old", [mid1, mid2])

        now = 10_000_000
        window_minutes = 60
        # One anomaly well within window, one outside
        await _insert_anomaly(tmp_store, mid1, now - 30_000)  # 30s ago — in window
        await _insert_anomaly(
            tmp_store, mid2, now - (window_minutes * 60 * 1000 + 1_000)
        )  # just outside window

        correlator = ClusterCorrelator(
            tmp_store, min_cluster_markets=2, cluster_window_minutes=window_minutes
        )
        result = await correlator.correlate(now_ms=now)
        assert result == []

    async def test_correlate_and_store(self, tmp_store):
        """correlate_and_store persists cluster anomalies."""
        mid1 = await _insert_market(tmp_store, "CORR-H1")
        mid2 = await _insert_market(tmp_store, "CORR-H2")
        await _create_cluster(tmp_store, "Stored", [mid1, mid2])

        now = 1_000_000
        await _insert_anomaly(tmp_store, mid1, now - 60_000)
        await _insert_anomaly(tmp_store, mid2, now - 30_000)

        correlator = ClusterCorrelator(
            tmp_store, min_cluster_markets=2, cluster_window_minutes=60
        )
        count = await correlator.correlate_and_store(now_ms=now)
        assert count == 1

        # Verify stored
        stored = await tmp_store.get_anomalies(
            anomaly_type=AnomalyType.CLUSTER.value
        )
        assert len(stored) == 1
        assert stored[0].anomaly_type == AnomalyType.CLUSTER

    async def test_deduplication(self, tmp_store):
        """Same cluster doesn't fire twice in the same window."""
        mid1 = await _insert_market(tmp_store, "CORR-I1")
        mid2 = await _insert_market(tmp_store, "CORR-I2")
        cid = await _create_cluster(tmp_store, "Dedup", [mid1, mid2])

        now = 1_000_000
        await _insert_anomaly(tmp_store, mid1, now - 60_000)
        await _insert_anomaly(tmp_store, mid2, now - 30_000)

        correlator = ClusterCorrelator(
            tmp_store, min_cluster_markets=2, cluster_window_minutes=60
        )

        # First run
        count1 = await correlator.correlate_and_store(now_ms=now)
        assert count1 == 1

        # Second run — should not emit again
        count2 = await correlator.correlate_and_store(now_ms=now)
        assert count2 == 0

    async def test_multiple_clusters_independent(self, tmp_store):
        """Two clusters fire independently."""
        mid1 = await _insert_market(tmp_store, "CORR-J1")
        mid2 = await _insert_market(tmp_store, "CORR-J2")
        mid3 = await _insert_market(tmp_store, "CORR-J3")
        mid4 = await _insert_market(tmp_store, "CORR-J4")

        await _create_cluster(tmp_store, "ClusterA", [mid1, mid2])
        await _create_cluster(tmp_store, "ClusterB", [mid3, mid4])

        now = 1_000_000
        await _insert_anomaly(tmp_store, mid1, now - 60_000)
        await _insert_anomaly(tmp_store, mid2, now - 30_000)
        await _insert_anomaly(tmp_store, mid3, now - 45_000)
        await _insert_anomaly(tmp_store, mid4, now - 15_000)

        correlator = ClusterCorrelator(
            tmp_store, min_cluster_markets=2, cluster_window_minutes=60
        )
        result = await correlator.correlate(now_ms=now)
        assert len(result) == 2

    async def test_summary_format(self, tmp_store):
        """Summary contains cluster name, count, and direction."""
        mid1 = await _insert_market(tmp_store, "CORR-K1")
        mid2 = await _insert_market(tmp_store, "CORR-K2")
        await _create_cluster(tmp_store, "Crypto", [mid1, mid2])

        now = 1_000_000
        await _insert_anomaly(
            tmp_store, mid1, now - 60_000,
            summary="market_id=1: +20.0% price in 5min window",
        )
        await _insert_anomaly(
            tmp_store, mid2, now - 30_000,
            summary="market_id=2: +15.0% price in 5min window",
        )

        correlator = ClusterCorrelator(
            tmp_store, min_cluster_markets=2, cluster_window_minutes=60
        )
        result = await correlator.correlate(now_ms=now)

        assert len(result) == 1
        summary = result[0].summary
        assert "Crypto" in summary
        assert "2 markets" in summary
        assert "bullish" in summary

    async def test_min_cluster_markets_configurable(self, tmp_store):
        """min=2 fires with 2 anomalous, min=3 does not."""
        mid1 = await _insert_market(tmp_store, "CORR-L1")
        mid2 = await _insert_market(tmp_store, "CORR-L2")
        mid3 = await _insert_market(tmp_store, "CORR-L3")
        await _create_cluster(tmp_store, "Config", [mid1, mid2, mid3])

        now = 1_000_000
        await _insert_anomaly(tmp_store, mid1, now - 60_000)
        await _insert_anomaly(tmp_store, mid2, now - 30_000)
        # mid3 has no anomaly

        # min=2 should fire
        corr2 = ClusterCorrelator(
            tmp_store, min_cluster_markets=2, cluster_window_minutes=60
        )
        result2 = await corr2.correlate(now_ms=now)
        assert len(result2) == 1

        # min=3 should NOT fire (only 2 anomalous)
        corr3 = ClusterCorrelator(
            tmp_store, min_cluster_markets=3, cluster_window_minutes=60
        )
        result3 = await corr3.correlate(now_ms=now)
        assert len(result3) == 0
