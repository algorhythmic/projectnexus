"""PostgreSQL integration tests for PostgresStore.

These tests require a running PostgreSQL instance and the
TEST_POSTGRES_DSN environment variable to be set, e.g.:
    export TEST_POSTGRES_DSN="postgresql://user:pass@localhost/nexus_test"

Run with:  python -m poetry run pytest tests/test_postgres.py -v
"""

import time

import pytest

from nexus.core.types import (
    AnomalyMarketRecord,
    AnomalyRecord,
    AnomalyStatus,
    AnomalyType,
    DiscoveredMarket,
    EventRecord,
    EventType,
    Platform,
    TopicCluster,
)

pytestmark = pytest.mark.postgres


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _now_ms() -> int:
    return int(time.time() * 1000)


def _make_market(
    external_id: str = "MKT-1",
    platform: Platform = Platform.KALSHI,
    title: str = "Will X happen?",
) -> DiscoveredMarket:
    return DiscoveredMarket(
        platform=platform,
        external_id=external_id,
        title=title,
        description="Test market",
        category="test",
        is_active=True,
    )


def _make_event(market_id: int, ts: int = 0, event_type: EventType = EventType.PRICE_CHANGE) -> EventRecord:
    return EventRecord(
        market_id=market_id,
        event_type=event_type,
        old_value=0.5,
        new_value=0.6,
        timestamp=ts or _now_ms(),
    )


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


async def test_upsert_markets(pg_store):
    m1 = _make_market("EXT-1", title="Market A")
    m2 = _make_market("EXT-2", title="Market B")

    new_count = await pg_store.upsert_markets([m1, m2])
    assert new_count == 2

    # Upsert again — should update, not insert
    new_count2 = await pg_store.upsert_markets([m1, m2])
    assert new_count2 == 0

    total = await pg_store.get_market_count()
    assert total == 2


async def test_get_market_by_external_id(pg_store):
    m = _make_market("EXT-FIND")
    await pg_store.upsert_markets([m])

    found = await pg_store.get_market_by_external_id("kalshi", "EXT-FIND")
    assert found is not None
    assert found.external_id == "EXT-FIND"
    assert found.platform == Platform.KALSHI

    missing = await pg_store.get_market_by_external_id("kalshi", "NOPE")
    assert missing is None


async def test_get_active_markets(pg_store):
    m1 = _make_market("ACT-1", platform=Platform.KALSHI)
    m2 = _make_market("ACT-2", platform=Platform.POLYMARKET)
    await pg_store.upsert_markets([m1, m2])

    all_active = await pg_store.get_active_markets()
    assert len(all_active) == 2

    kalshi_only = await pg_store.get_active_markets(platform="kalshi")
    assert len(kalshi_only) == 1
    assert kalshi_only[0].platform == Platform.KALSHI


async def test_insert_and_get_events(pg_store):
    await pg_store.upsert_markets([_make_market("EVT-1")])
    market = await pg_store.get_market_by_external_id("kalshi", "EVT-1")

    now = _now_ms()
    events = [
        _make_event(market.id, ts=now - 2000),
        _make_event(market.id, ts=now - 1000),
        _make_event(market.id, ts=now),
    ]
    inserted = await pg_store.insert_events(events)
    assert inserted == 3

    total = await pg_store.get_event_count()
    assert total == 3

    # Query by market
    found = await pg_store.get_events(market_id=market.id)
    assert len(found) == 3


async def test_event_time_range(pg_store):
    await pg_store.upsert_markets([_make_market("TR-1")])
    market = await pg_store.get_market_by_external_id("kalshi", "TR-1")

    ts1 = 1000000
    ts2 = 2000000
    await pg_store.insert_events([
        _make_event(market.id, ts=ts1),
        _make_event(market.id, ts=ts2),
    ])

    min_ts, max_ts = await pg_store.get_event_time_range()
    assert min_ts == ts1
    assert max_ts == ts2


async def test_empty_event_time_range(pg_store):
    min_ts, max_ts = await pg_store.get_event_time_range()
    assert min_ts is None
    assert max_ts is None


async def test_event_count_in_range(pg_store):
    await pg_store.upsert_markets([_make_market("RNG-1")])
    market = await pg_store.get_market_by_external_id("kalshi", "RNG-1")

    await pg_store.insert_events([
        _make_event(market.id, ts=100),
        _make_event(market.id, ts=200),
        _make_event(market.id, ts=300),
    ])

    count = await pg_store.get_event_count_in_range(since=150, until=250)
    assert count == 1  # only ts=200


async def test_duplicate_event_count(pg_store):
    await pg_store.upsert_markets([_make_market("DUP-1")])
    market = await pg_store.get_market_by_external_id("kalshi", "DUP-1")

    e = _make_event(market.id, ts=1000)
    await pg_store.insert_events([e, e])  # duplicate

    dups = await pg_store.get_duplicate_event_count()
    assert dups == 1


async def test_event_type_distribution(pg_store):
    await pg_store.upsert_markets([_make_market("DIST-1")])
    market = await pg_store.get_market_by_external_id("kalshi", "DIST-1")

    events = [
        _make_event(market.id, ts=100, event_type=EventType.PRICE_CHANGE),
        _make_event(market.id, ts=200, event_type=EventType.PRICE_CHANGE),
        _make_event(market.id, ts=300, event_type=EventType.VOLUME_UPDATE),
    ]
    await pg_store.insert_events(events)

    dist = await pg_store.get_event_type_distribution()
    assert dist["price_change"] == 2
    assert dist["volume_update"] == 1


async def test_anomaly_lifecycle(pg_store):
    await pg_store.upsert_markets([_make_market("ANOM-1")])
    market = await pg_store.get_market_by_external_id("kalshi", "ANOM-1")
    now = _now_ms()

    anomaly = AnomalyRecord(
        anomaly_type=AnomalyType.SINGLE_MARKET,
        severity=0.75,
        market_count=1,
        window_start=now - 60000,
        detected_at=now,
        summary="Test anomaly",
        status=AnomalyStatus.ACTIVE,
    )
    link = AnomalyMarketRecord(
        anomaly_id=0,  # will be set by insert
        market_id=market.id,
        price_delta=0.15,
        volume_ratio=2.5,
    )
    aid = await pg_store.insert_anomaly(anomaly, [link])
    assert aid > 0

    # Query
    results = await pg_store.get_anomalies(since=now - 1000)
    assert len(results) == 1
    assert results[0].severity == 0.75

    # Get markets
    links = await pg_store.get_anomaly_markets(aid)
    assert len(links) == 1
    assert links[0].market_id == market.id

    # Update status
    await pg_store.update_anomaly_status(aid, AnomalyStatus.ACKNOWLEDGED)
    updated = await pg_store.get_anomalies(status=AnomalyStatus.ACKNOWLEDGED)
    assert len(updated) == 1


async def test_expire_old_anomalies(pg_store):
    await pg_store.upsert_markets([_make_market("EXP-1")])
    market = await pg_store.get_market_by_external_id("kalshi", "EXP-1")
    now = _now_ms()

    old = AnomalyRecord(
        anomaly_type=AnomalyType.SINGLE_MARKET,
        severity=0.5,
        market_count=1,
        window_start=now - 200000,
        detected_at=now - 100000,
        status=AnomalyStatus.ACTIVE,
    )
    recent = AnomalyRecord(
        anomaly_type=AnomalyType.SINGLE_MARKET,
        severity=0.5,
        market_count=1,
        window_start=now - 10000,
        detected_at=now,
        status=AnomalyStatus.ACTIVE,
    )
    link = AnomalyMarketRecord(anomaly_id=0, market_id=market.id)

    await pg_store.insert_anomaly(old, [link])
    await pg_store.insert_anomaly(recent, [link])

    expired_count = await pg_store.expire_old_anomalies(now - 50000)
    assert expired_count == 1

    active = await pg_store.get_anomalies(status=AnomalyStatus.ACTIVE)
    assert len(active) == 1


async def test_topic_clusters(pg_store):
    now = _now_ms()
    cluster = TopicCluster(
        name="US Elections",
        description="Markets about US elections",
        created_at=now,
        updated_at=now,
    )
    cid = await pg_store.insert_cluster(cluster)
    assert cid > 0

    clusters = await pg_store.get_clusters()
    assert len(clusters) == 1
    assert clusters[0].name == "US Elections"

    found = await pg_store.get_cluster_by_name("US Elections")
    assert found is not None
    assert found.id == cid

    missing = await pg_store.get_cluster_by_name("Nonexistent")
    assert missing is None


async def test_cluster_market_assignment(pg_store):
    await pg_store.upsert_markets([_make_market("CLU-1"), _make_market("CLU-2")])
    m1 = await pg_store.get_market_by_external_id("kalshi", "CLU-1")
    m2 = await pg_store.get_market_by_external_id("kalshi", "CLU-2")

    now = _now_ms()
    cid = await pg_store.insert_cluster(TopicCluster(
        name="Tech", description="Tech markets", created_at=now, updated_at=now,
    ))

    await pg_store.assign_market_to_cluster(m1.id, cid, 0.95)
    await pg_store.assign_market_to_cluster(m2.id, cid, 0.80)

    members = await pg_store.get_cluster_markets(cid)
    assert len(members) == 2

    # Check reverse lookup
    m1_clusters = await pg_store.get_market_clusters(m1.id)
    assert len(m1_clusters) == 1
    assert m1_clusters[0][1] == "Tech"
    assert m1_clusters[0][2] == 0.95


async def test_unassigned_markets(pg_store):
    await pg_store.upsert_markets([_make_market("UA-1"), _make_market("UA-2")])
    m1 = await pg_store.get_market_by_external_id("kalshi", "UA-1")

    now = _now_ms()
    cid = await pg_store.insert_cluster(TopicCluster(
        name="Assigned", created_at=now, updated_at=now,
    ))
    await pg_store.assign_market_to_cluster(m1.id, cid, 0.9)

    unassigned = await pg_store.get_unassigned_markets()
    assert len(unassigned) == 1
    assert unassigned[0].external_id == "UA-2"


async def test_store_factory_postgres():
    """Test that create_store returns PostgresStore when backend=postgres."""
    from nexus.store import create_store

    class FakeSettings:
        store_backend = "postgres"
        postgres_dsn = "postgresql://user:pass@localhost/db"
        postgres_pool_min = 1
        postgres_pool_max = 3

    store = create_store(FakeSettings())
    from nexus.store.postgres import PostgresStore
    assert isinstance(store, PostgresStore)


async def test_store_factory_sqlite(tmp_path):
    """Test that create_store returns SQLiteStore when backend=sqlite."""
    from nexus.store import create_store
    from nexus.store.sqlite import SQLiteStore

    class FakeSettings:
        store_backend = "sqlite"
        sqlite_path = str(tmp_path / "test.db")

    store = create_store(FakeSettings())
    assert isinstance(store, SQLiteStore)
