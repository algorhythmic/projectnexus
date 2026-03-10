"""Tests for cross-platform link storage and event pruning (Milestone 3.3)."""

import time

import pytest

from nexus.core.types import (
    CrossPlatformLink,
    DiscoveredMarket,
    EventRecord,
    EventType,
    Platform,
)


NOW_MS = int(time.time() * 1000)


async def _insert_markets(store):
    """Insert two markets on different platforms. Returns (m1_id, m2_id)."""
    await store.upsert_markets([
        DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="kalshi-1",
            title="Will X happen?",
        ),
        DiscoveredMarket(
            platform=Platform.POLYMARKET,
            external_id="poly-1",
            title="Will X happen? (Polymarket)",
        ),
    ])
    m1 = await store.get_market_by_external_id("kalshi", "kalshi-1")
    m2 = await store.get_market_by_external_id("polymarket", "poly-1")
    return m1.id, m2.id


# ------------------------------------------------------------------
# Cross-platform link tests
# ------------------------------------------------------------------


class TestCrossPlatformLinks:
    async def test_upsert_and_get(self, tmp_store):
        m1, m2 = await _insert_markets(tmp_store)
        link = CrossPlatformLink(
            market_id_a=m1, market_id_b=m2,
            confidence=0.85, method="cluster", created_at=NOW_MS,
        )
        link_id = await tmp_store.upsert_cross_platform_link(link)
        assert link_id is not None

        links = await tmp_store.get_cross_platform_links()
        assert len(links) == 1
        assert links[0].confidence == 0.85
        assert links[0].method == "cluster"

    async def test_get_by_market_id(self, tmp_store):
        m1, m2 = await _insert_markets(tmp_store)
        link = CrossPlatformLink(
            market_id_a=m1, market_id_b=m2,
            confidence=0.9, method="cluster", created_at=NOW_MS,
        )
        await tmp_store.upsert_cross_platform_link(link)

        # Both directions should find the link
        links_a = await tmp_store.get_cross_platform_links(market_id=m1)
        links_b = await tmp_store.get_cross_platform_links(market_id=m2)
        assert len(links_a) == 1
        assert len(links_b) == 1

    async def test_get_pair(self, tmp_store):
        m1, m2 = await _insert_markets(tmp_store)
        link = CrossPlatformLink(
            market_id_a=m1, market_id_b=m2,
            confidence=0.75, method="cluster", created_at=NOW_MS,
        )
        await tmp_store.upsert_cross_platform_link(link)

        # Order shouldn't matter
        found = await tmp_store.get_cross_platform_pair(m2, m1)
        assert found is not None
        assert found.confidence == 0.75

    async def test_get_pair_not_found(self, tmp_store):
        m1, m2 = await _insert_markets(tmp_store)
        found = await tmp_store.get_cross_platform_pair(m1, m2)
        assert found is None

    async def test_upsert_updates_existing(self, tmp_store):
        m1, m2 = await _insert_markets(tmp_store)
        link1 = CrossPlatformLink(
            market_id_a=m1, market_id_b=m2,
            confidence=0.7, method="cluster", created_at=NOW_MS,
        )
        await tmp_store.upsert_cross_platform_link(link1)

        link2 = CrossPlatformLink(
            market_id_a=m1, market_id_b=m2,
            confidence=0.95, method="cluster", created_at=NOW_MS + 1000,
        )
        await tmp_store.upsert_cross_platform_link(link2)

        links = await tmp_store.get_cross_platform_links()
        assert len(links) == 1
        assert links[0].confidence == 0.95

    async def test_normalized_ordering(self, tmp_store):
        """Links are stored with lower market_id first."""
        m1, m2 = await _insert_markets(tmp_store)
        # Insert with reversed order
        link = CrossPlatformLink(
            market_id_a=m2, market_id_b=m1,
            confidence=0.8, method="cluster", created_at=NOW_MS,
        )
        await tmp_store.upsert_cross_platform_link(link)

        links = await tmp_store.get_cross_platform_links()
        assert len(links) == 1
        assert links[0].market_id_a == min(m1, m2)
        assert links[0].market_id_b == max(m1, m2)


# ------------------------------------------------------------------
# Event pruning tests
# ------------------------------------------------------------------


class TestEventPruning:
    async def test_prune_deletes_old_events(self, tmp_store):
        m1, m2 = await _insert_markets(tmp_store)
        old_ts = NOW_MS - 100_000_000  # ~27 hours ago
        new_ts = NOW_MS - 1000

        events = [
            EventRecord(market_id=m1, event_type=EventType.PRICE_CHANGE,
                        new_value=0.5, timestamp=old_ts),
            EventRecord(market_id=m1, event_type=EventType.PRICE_CHANGE,
                        new_value=0.6, timestamp=old_ts + 1000),
            EventRecord(market_id=m1, event_type=EventType.PRICE_CHANGE,
                        new_value=0.7, timestamp=new_ts),
        ]
        await tmp_store.insert_events(events)
        assert await tmp_store.get_event_count() == 3

        # Prune events older than 1 hour
        cutoff = NOW_MS - 3600_000
        pruned = await tmp_store.prune_events(cutoff)
        assert pruned == 2
        assert await tmp_store.get_event_count() == 1

    async def test_prune_no_old_events(self, tmp_store):
        m1, m2 = await _insert_markets(tmp_store)
        events = [
            EventRecord(market_id=m1, event_type=EventType.PRICE_CHANGE,
                        new_value=0.5, timestamp=NOW_MS - 1000),
        ]
        await tmp_store.insert_events(events)

        pruned = await tmp_store.prune_events(NOW_MS - 86400_000)
        assert pruned == 0
        assert await tmp_store.get_event_count() == 1

    async def test_prune_empty_store(self, tmp_store):
        pruned = await tmp_store.prune_events(NOW_MS)
        assert pruned == 0
