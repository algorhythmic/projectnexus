"""Tests for topic cluster store CRUD operations."""

import time

import pytest

from nexus.core.types import (
    DiscoveredMarket,
    Platform,
    TopicCluster,
)


async def _insert_market(store, external_id: str = "CL-TEST") -> int:
    market = DiscoveredMarket(
        platform=Platform.KALSHI,
        external_id=external_id,
        title=f"Cluster Test {external_id}",
        yes_price=0.5,
    )
    await store.upsert_markets([market])
    stored = await store.get_market_by_external_id("kalshi", external_id)
    return stored.id


def _make_cluster(name: str = "Test Cluster", desc: str = None) -> TopicCluster:
    now = int(time.time() * 1000)
    return TopicCluster(
        name=name,
        description=desc,
        created_at=now,
        updated_at=now,
    )


class TestClusterStore:
    async def test_insert_cluster(self, tmp_store):
        """Insert a cluster and get a valid id."""
        cid = await tmp_store.insert_cluster(_make_cluster("Fed Policy"))
        assert cid > 0

    async def test_get_clusters_empty(self, tmp_store):
        """No clusters returns empty list."""
        clusters = await tmp_store.get_clusters()
        assert clusters == []

    async def test_get_clusters_multiple(self, tmp_store):
        """Insert multiple clusters and retrieve them sorted by name."""
        await tmp_store.insert_cluster(_make_cluster("Crypto"))
        await tmp_store.insert_cluster(_make_cluster("AI Policy"))
        await tmp_store.insert_cluster(_make_cluster("Sports"))

        clusters = await tmp_store.get_clusters()
        assert len(clusters) == 3
        assert clusters[0].name == "AI Policy"
        assert clusters[1].name == "Crypto"
        assert clusters[2].name == "Sports"

    async def test_get_cluster_by_name_found(self, tmp_store):
        """Exact name lookup succeeds."""
        await tmp_store.insert_cluster(_make_cluster("Fed Policy", "Interest rate markets"))
        cluster = await tmp_store.get_cluster_by_name("Fed Policy")
        assert cluster is not None
        assert cluster.name == "Fed Policy"
        assert cluster.description == "Interest rate markets"

    async def test_get_cluster_by_name_not_found(self, tmp_store):
        """Non-existent name returns None."""
        result = await tmp_store.get_cluster_by_name("Nonexistent")
        assert result is None

    async def test_assign_market_to_cluster(self, tmp_store):
        """Assign a market and retrieve via get_cluster_markets."""
        mid = await _insert_market(tmp_store)
        cid = await tmp_store.insert_cluster(_make_cluster("Test"))

        await tmp_store.assign_market_to_cluster(mid, cid, 0.95)
        markets = await tmp_store.get_cluster_markets(cid)

        assert len(markets) == 1
        assert markets[0] == (mid, 0.95)

    async def test_assign_market_to_cluster_update(self, tmp_store):
        """Re-assigning updates the confidence score."""
        mid = await _insert_market(tmp_store)
        cid = await tmp_store.insert_cluster(_make_cluster("Test"))

        await tmp_store.assign_market_to_cluster(mid, cid, 0.5)
        await tmp_store.assign_market_to_cluster(mid, cid, 0.9)

        markets = await tmp_store.get_cluster_markets(cid)
        assert len(markets) == 1
        assert markets[0][1] == 0.9

    async def test_get_cluster_markets_empty(self, tmp_store):
        """Cluster with no markets returns empty list."""
        cid = await tmp_store.insert_cluster(_make_cluster("Empty"))
        markets = await tmp_store.get_cluster_markets(cid)
        assert markets == []

    async def test_get_cluster_markets_multiple(self, tmp_store):
        """Multiple markets assigned to one cluster."""
        mid1 = await _insert_market(tmp_store, "CL-1")
        mid2 = await _insert_market(tmp_store, "CL-2")
        cid = await tmp_store.insert_cluster(_make_cluster("Multi"))

        await tmp_store.assign_market_to_cluster(mid1, cid, 0.8)
        await tmp_store.assign_market_to_cluster(mid2, cid, 0.7)

        markets = await tmp_store.get_cluster_markets(cid)
        assert len(markets) == 2

    async def test_get_market_clusters(self, tmp_store):
        """Market assigned to two clusters returns both."""
        mid = await _insert_market(tmp_store)
        cid1 = await tmp_store.insert_cluster(_make_cluster("Cluster A"))
        cid2 = await tmp_store.insert_cluster(_make_cluster("Cluster B"))

        await tmp_store.assign_market_to_cluster(mid, cid1, 0.9)
        await tmp_store.assign_market_to_cluster(mid, cid2, 0.6)

        clusters = await tmp_store.get_market_clusters(mid)
        assert len(clusters) == 2
        names = {c[1] for c in clusters}
        assert names == {"Cluster A", "Cluster B"}

    async def test_get_unassigned_markets(self, tmp_store):
        """Only unassigned active markets returned."""
        mid1 = await _insert_market(tmp_store, "ASSIGNED")
        mid2 = await _insert_market(tmp_store, "UNASSIGNED")
        cid = await tmp_store.insert_cluster(_make_cluster("Test"))

        await tmp_store.assign_market_to_cluster(mid1, cid, 0.9)

        unassigned = await tmp_store.get_unassigned_markets()
        assert len(unassigned) == 1
        assert unassigned[0].id == mid2

    async def test_get_unassigned_markets_all_assigned(self, tmp_store):
        """All markets assigned returns empty list."""
        mid = await _insert_market(tmp_store)
        cid = await tmp_store.insert_cluster(_make_cluster("Test"))
        await tmp_store.assign_market_to_cluster(mid, cid, 0.9)

        unassigned = await tmp_store.get_unassigned_markets()
        assert unassigned == []
