"""Tests for anomaly store CRUD operations."""

import time

import pytest

from nexus.core.types import (
    AnomalyMarketRecord,
    AnomalyRecord,
    AnomalyStatus,
    AnomalyType,
    DiscoveredMarket,
    Platform,
)


async def _insert_market(store, external_id: str = "ANOM-TEST") -> int:
    """Insert a test market and return its id."""
    market = DiscoveredMarket(
        platform=Platform.KALSHI,
        external_id=external_id,
        title=f"Anomaly Test {external_id}",
        yes_price=0.5,
    )
    await store.upsert_markets([market])
    stored = await store.get_market_by_external_id("kalshi", external_id)
    return stored.id


def _make_anomaly(
    severity: float = 0.8,
    detected_at: int = 1000000,
    status: AnomalyStatus = AnomalyStatus.ACTIVE,
) -> AnomalyRecord:
    return AnomalyRecord(
        anomaly_type=AnomalyType.SINGLE_MARKET,
        severity=severity,
        market_count=1,
        window_start=detected_at - 300_000,
        detected_at=detected_at,
        summary="test anomaly",
        status=status,
    )


class TestAnomalyStore:
    async def test_insert_and_get(self, tmp_store):
        """Insert an anomaly and retrieve it."""
        mid = await _insert_market(tmp_store)
        anomaly = _make_anomaly()
        links = [AnomalyMarketRecord(anomaly_id=0, market_id=mid)]

        aid = await tmp_store.insert_anomaly(anomaly, links)
        assert aid > 0

        results = await tmp_store.get_anomalies()
        assert len(results) == 1
        assert results[0].id == aid
        assert results[0].severity == 0.8
        assert results[0].anomaly_type == AnomalyType.SINGLE_MARKET

    async def test_get_anomaly_markets(self, tmp_store):
        """Junction rows are stored and retrievable."""
        mid = await _insert_market(tmp_store)
        anomaly = _make_anomaly()
        links = [AnomalyMarketRecord(
            anomaly_id=0, market_id=mid,
            price_delta=0.15, volume_ratio=3.5,
        )]

        aid = await tmp_store.insert_anomaly(anomaly, links)
        markets = await tmp_store.get_anomaly_markets(aid)

        assert len(markets) == 1
        assert markets[0].market_id == mid
        assert markets[0].price_delta == 0.15
        assert markets[0].volume_ratio == 3.5

    async def test_filter_by_severity(self, tmp_store):
        """get_anomalies filters by min_severity."""
        mid = await _insert_market(tmp_store)

        await tmp_store.insert_anomaly(
            _make_anomaly(severity=0.3, detected_at=1000000),
            [AnomalyMarketRecord(anomaly_id=0, market_id=mid)],
        )
        await tmp_store.insert_anomaly(
            _make_anomaly(severity=0.9, detected_at=2000000),
            [AnomalyMarketRecord(anomaly_id=0, market_id=mid)],
        )

        results = await tmp_store.get_anomalies(min_severity=0.5)
        assert len(results) == 1
        assert results[0].severity == 0.9

    async def test_filter_by_status(self, tmp_store):
        """get_anomalies filters by status."""
        mid = await _insert_market(tmp_store)

        await tmp_store.insert_anomaly(
            _make_anomaly(detected_at=1000000),
            [AnomalyMarketRecord(anomaly_id=0, market_id=mid)],
        )
        await tmp_store.insert_anomaly(
            _make_anomaly(status=AnomalyStatus.EXPIRED, detected_at=2000000),
            [AnomalyMarketRecord(anomaly_id=0, market_id=mid)],
        )

        active = await tmp_store.get_anomalies(status=AnomalyStatus.ACTIVE)
        assert len(active) == 1

        expired = await tmp_store.get_anomalies(status=AnomalyStatus.EXPIRED)
        assert len(expired) == 1

    async def test_filter_by_market_id(self, tmp_store):
        """get_anomalies filters by market_id through junction table."""
        mid1 = await _insert_market(tmp_store, "MKT-1")
        mid2 = await _insert_market(tmp_store, "MKT-2")

        await tmp_store.insert_anomaly(
            _make_anomaly(detected_at=1000000),
            [AnomalyMarketRecord(anomaly_id=0, market_id=mid1)],
        )
        await tmp_store.insert_anomaly(
            _make_anomaly(detected_at=2000000),
            [AnomalyMarketRecord(anomaly_id=0, market_id=mid2)],
        )

        results = await tmp_store.get_anomalies(market_id=mid1)
        assert len(results) == 1

    async def test_update_anomaly_status(self, tmp_store):
        """update_anomaly_status changes the status."""
        mid = await _insert_market(tmp_store)
        aid = await tmp_store.insert_anomaly(
            _make_anomaly(),
            [AnomalyMarketRecord(anomaly_id=0, market_id=mid)],
        )

        await tmp_store.update_anomaly_status(aid, AnomalyStatus.ACKNOWLEDGED)
        results = await tmp_store.get_anomalies()
        assert results[0].status == AnomalyStatus.ACKNOWLEDGED

    async def test_expire_old_anomalies(self, tmp_store):
        """expire_old_anomalies bulk-expires old active anomalies."""
        mid = await _insert_market(tmp_store)

        # Old anomaly
        await tmp_store.insert_anomaly(
            _make_anomaly(detected_at=1000000),
            [AnomalyMarketRecord(anomaly_id=0, market_id=mid)],
        )
        # Recent anomaly
        await tmp_store.insert_anomaly(
            _make_anomaly(detected_at=9000000),
            [AnomalyMarketRecord(anomaly_id=0, market_id=mid)],
        )

        expired = await tmp_store.expire_old_anomalies(5000000)
        assert expired == 1

        active = await tmp_store.get_anomalies(status=AnomalyStatus.ACTIVE)
        assert len(active) == 1
        assert active[0].detected_at == 9000000

    async def test_filter_by_time_range(self, tmp_store):
        """get_anomalies filters by since/until."""
        mid = await _insert_market(tmp_store)

        await tmp_store.insert_anomaly(
            _make_anomaly(detected_at=1000000),
            [AnomalyMarketRecord(anomaly_id=0, market_id=mid)],
        )
        await tmp_store.insert_anomaly(
            _make_anomaly(detected_at=5000000),
            [AnomalyMarketRecord(anomaly_id=0, market_id=mid)],
        )

        results = await tmp_store.get_anomalies(since=3000000)
        assert len(results) == 1
        assert results[0].detected_at == 5000000
