"""Tests for the SQLite event store."""

import pytest

from nexus.core.types import (
    DiscoveredMarket,
    EventRecord,
    EventType,
    Platform,
)


class TestSQLiteStoreInitialize:
    async def test_creates_tables(self, tmp_store):
        """initialize() creates the markets and events tables."""
        cursor = await tmp_store.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in await cursor.fetchall()]
        assert "markets" in tables
        assert "events" in tables

    async def test_creates_indexes(self, tmp_store):
        """initialize() creates the expected indexes."""
        cursor = await tmp_store.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        indexes = {row[0] for row in await cursor.fetchall()}
        assert "idx_markets_platform" in indexes
        assert "idx_events_timestamp" in indexes


class TestUpsertMarkets:
    async def test_insert_new_market(self, tmp_store):
        """Inserting a new market returns count=1."""
        market = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="TEST-MKT-1",
            title="Test Market",
            category="Politics",
        )
        count = await tmp_store.upsert_markets([market])
        assert count == 1

    async def test_upsert_existing_market_updates(self, tmp_store):
        """Upserting an existing market updates it and returns count=0."""
        market = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="TEST-MKT-1",
            title="Original Title",
            category="Politics",
        )
        await tmp_store.upsert_markets([market])

        updated = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="TEST-MKT-1",
            title="Updated Title",
            category="Economics",
        )
        count = await tmp_store.upsert_markets([updated])
        assert count == 0

        stored = await tmp_store.get_market_by_external_id(
            "kalshi", "TEST-MKT-1"
        )
        assert stored is not None
        assert stored.title == "Updated Title"
        assert stored.category == "Economics"

    async def test_upsert_multiple_platforms(self, tmp_store):
        """Markets with same external_id on different platforms are distinct."""
        m1 = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="SAME-ID",
            title="Kalshi Version",
        )
        m2 = DiscoveredMarket(
            platform=Platform.POLYMARKET,
            external_id="SAME-ID",
            title="Polymarket Version",
        )
        count = await tmp_store.upsert_markets([m1, m2])
        assert count == 2


class TestGetMarkets:
    async def test_get_by_external_id(self, tmp_store):
        """Lookup by platform + external_id."""
        market = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="LOOKUP-1",
            title="Lookup Test",
        )
        await tmp_store.upsert_markets([market])

        found = await tmp_store.get_market_by_external_id("kalshi", "LOOKUP-1")
        assert found is not None
        assert found.external_id == "LOOKUP-1"

    async def test_get_nonexistent_returns_none(self, tmp_store):
        result = await tmp_store.get_market_by_external_id("kalshi", "NOPE")
        assert result is None

    async def test_get_active_markets_filters_by_platform(self, tmp_store):
        """get_active_markets with platform filter works."""
        m1 = DiscoveredMarket(
            platform=Platform.KALSHI, external_id="K1", title="K"
        )
        m2 = DiscoveredMarket(
            platform=Platform.POLYMARKET, external_id="P1", title="P"
        )
        await tmp_store.upsert_markets([m1, m2])

        kalshi_only = await tmp_store.get_active_markets(platform="kalshi")
        assert len(kalshi_only) == 1
        assert kalshi_only[0].platform == Platform.KALSHI


class TestEvents:
    async def test_insert_and_get_events(self, tmp_store):
        """Round-trip: insert events then query them back."""
        # Create a market first
        market = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="EVT-MKT",
            title="Event Test",
        )
        await tmp_store.upsert_markets([market])
        stored = await tmp_store.get_market_by_external_id("kalshi", "EVT-MKT")
        assert stored is not None and stored.id is not None

        events = [
            EventRecord(
                market_id=stored.id,
                event_type=EventType.NEW_MARKET,
                new_value=0.55,
                timestamp=1000,
            ),
            EventRecord(
                market_id=stored.id,
                event_type=EventType.PRICE_CHANGE,
                old_value=0.55,
                new_value=0.60,
                timestamp=2000,
            ),
        ]
        inserted = await tmp_store.insert_events(events)
        assert inserted == 2

        fetched = await tmp_store.get_events(market_id=stored.id)
        assert len(fetched) == 2
        # Most recent first
        assert fetched[0].new_value == 0.60

    async def test_get_events_filters_by_type(self, tmp_store):
        """Filtering events by event_type."""
        market = DiscoveredMarket(
            platform=Platform.KALSHI, external_id="FLT", title="Filter"
        )
        await tmp_store.upsert_markets([market])
        stored = await tmp_store.get_market_by_external_id("kalshi", "FLT")
        assert stored is not None and stored.id is not None

        events = [
            EventRecord(
                market_id=stored.id,
                event_type=EventType.NEW_MARKET,
                new_value=0.5,
                timestamp=1000,
            ),
            EventRecord(
                market_id=stored.id,
                event_type=EventType.PRICE_CHANGE,
                old_value=0.5,
                new_value=0.6,
                timestamp=2000,
            ),
        ]
        await tmp_store.insert_events(events)

        price_only = await tmp_store.get_events(event_type="price_change")
        assert len(price_only) == 1
        assert price_only[0].event_type == EventType.PRICE_CHANGE

    async def test_empty_insert_returns_zero(self, tmp_store):
        count = await tmp_store.insert_events([])
        assert count == 0


class TestStats:
    async def test_counts(self, tmp_store):
        """get_market_count and get_event_count return correct numbers."""
        assert await tmp_store.get_market_count() == 0
        assert await tmp_store.get_event_count() == 0

        market = DiscoveredMarket(
            platform=Platform.KALSHI, external_id="S1", title="Stats"
        )
        await tmp_store.upsert_markets([market])
        assert await tmp_store.get_market_count() == 1
