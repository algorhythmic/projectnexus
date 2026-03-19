"""Tests for the discovery polling loop."""

from typing import AsyncIterator, List, Sequence
from unittest.mock import AsyncMock

import pytest

from nexus.adapters.base import BaseAdapter
from nexus.core.types import DiscoveredMarket, EventRecord, Platform
from nexus.ingestion.discovery import DiscoveryLoop


class FakeAdapter(BaseAdapter):
    """A minimal adapter that returns canned data for testing."""

    def __init__(self, markets: List[DiscoveredMarket]) -> None:
        super().__init__(base_url="https://fake.api", rate_limit=100.0)
        self._markets = markets

    async def discover(self) -> List[DiscoveredMarket]:
        return self._markets

    async def connect(self, tickers: Sequence[str]) -> AsyncIterator[EventRecord]:
        raise NotImplementedError
        yield  # type: ignore[misc]  # pragma: no cover


class TestDiscoveryLoop:
    async def test_single_cycle_upserts_markets(self, tmp_store):
        """run_once upserts discovered markets into the store."""
        markets = [
            DiscoveredMarket(
                platform=Platform.KALSHI,
                external_id="DISC-1",
                title="Discovery Test",
                yes_price=0.65,
            ),
        ]
        adapter = FakeAdapter(markets)
        loop = DiscoveryLoop(
            adapters=[adapter], store=tmp_store, interval_seconds=0
        )

        results = await loop.run_once()
        assert results.get("FakeAdapter") == 1

        # Market should be in the store
        count = await tmp_store.get_market_count()
        assert count == 1

    async def test_first_cycle_generates_price_events(self, tmp_store):
        """First cycle (empty cache) emits price_change events for discovery seed."""
        m1 = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="SEED-1",
            title="Seed Price Test",
            yes_price=0.70,
        )
        adapter = FakeAdapter([m1])
        loop = DiscoveryLoop(
            adapters=[adapter], store=tmp_store, interval_seconds=0
        )

        await loop.run_once()

        events = await tmp_store.get_events()
        price_events = [e for e in events if e.event_type.value == "price_change"]
        assert len(price_events) >= 1
        assert price_events[0].new_value == 0.70
        assert price_events[0].old_value is None

    async def test_first_seen_market_emits_both_events(self, tmp_store):
        """A new market on cycle 2 gets both new_market and price_change events."""
        m1 = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="EXIST-1",
            title="Existing Market",
            yes_price=0.50,
        )
        adapter = FakeAdapter([m1])
        loop = DiscoveryLoop(
            adapters=[adapter], store=tmp_store, interval_seconds=0
        )

        # First cycle: seeds cache
        await loop.run_once()

        # Second cycle: add a brand-new market alongside the existing one
        m2 = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="NEW-1",
            title="Brand New Market",
            yes_price=0.40,
        )
        adapter._markets = [m1, m2]
        await loop.run_once()

        events = await tmp_store.get_events()
        # Filter to events for the new market
        # Need market_id for NEW-1 — look it up
        stored = await tmp_store.get_active_markets(platform="kalshi")
        new_market = [s for s in stored if s.external_id == "NEW-1"]
        assert len(new_market) == 1
        new_id = new_market[0].id

        new_events = [e for e in events if e.market_id == new_id]
        new_event_types = {e.event_type.value for e in new_events}
        assert "new_market" in new_event_types
        assert "price_change" in new_event_types

    async def test_seed_skips_null_price(self, tmp_store):
        """Markets with yes_price=None get no seed events on first cycle."""
        m1 = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="NULL-1",
            title="Null Price Market",
            yes_price=None,
        )
        adapter = FakeAdapter([m1])
        loop = DiscoveryLoop(
            adapters=[adapter], store=tmp_store, interval_seconds=0
        )

        await loop.run_once()

        events = await tmp_store.get_events()
        assert len(events) == 0

    async def test_second_cycle_generates_price_change_event(self, tmp_store):
        """Second cycle with different price generates a price_change event."""
        m1 = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="PRICE-1",
            title="Price Change Test",
            yes_price=0.50,
        )
        adapter = FakeAdapter([m1])
        loop = DiscoveryLoop(
            adapters=[adapter], store=tmp_store, interval_seconds=0
        )

        # First cycle: seeds cache + emits discovery_seed price events
        await loop.run_once()

        # Second cycle: same market, different price
        m2 = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="PRICE-1",
            title="Price Change Test",
            yes_price=0.65,
        )
        adapter._markets = [m2]
        await loop.run_once()

        events = await tmp_store.get_events()
        # First cycle emits a seed price_change (old_value=None).
        # Second cycle detects the actual price change (0.50 → 0.65).
        price_changes = [e for e in events if e.event_type.value == "price_change"]
        assert len(price_changes) >= 2
        # The latest price_change should have old_value=0.50
        actual_change = [e for e in price_changes if e.old_value is not None]
        assert len(actual_change) >= 1
        assert actual_change[0].old_value == 0.50
        assert actual_change[0].new_value == 0.65

    async def test_adapter_error_is_handled(self, tmp_store):
        """If an adapter raises, the loop logs it and continues."""
        adapter = FakeAdapter([])
        adapter.discover = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]

        loop = DiscoveryLoop(
            adapters=[adapter], store=tmp_store, interval_seconds=0
        )
        results = await loop.run_once()
        assert results.get("FakeAdapter") == 0

    async def test_stop_mechanism(self, tmp_store):
        """stop() sets _running to False."""
        adapter = FakeAdapter([])
        loop = DiscoveryLoop(
            adapters=[adapter], store=tmp_store, interval_seconds=0
        )
        loop._running = True
        await loop.stop()
        assert loop._running is False


class TestEndDateExpiry:
    async def test_expired_markets_deactivated(self, tmp_store):
        """run_once deactivates markets past their end_date."""
        # Insert a market with an end_date in the past
        expired = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="EXP-DISC-1",
            title="Expired Market",
            end_date="2020-01-01T00:00:00Z",
            yes_price=0.50,
        )
        adapter = FakeAdapter([expired])
        loop = DiscoveryLoop(
            adapters=[adapter], store=tmp_store, interval_seconds=0
        )

        await loop.run_once()

        stored = await tmp_store.get_market_by_external_id("kalshi", "EXP-DISC-1")
        assert stored is not None
        assert stored.is_active is False

    async def test_future_markets_stay_active(self, tmp_store):
        """run_once keeps markets with future end_date active."""
        future = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="FUT-DISC-1",
            title="Future Market",
            end_date="2030-12-31T23:59:59Z",
            yes_price=0.60,
        )
        adapter = FakeAdapter([future])
        loop = DiscoveryLoop(
            adapters=[adapter], store=tmp_store, interval_seconds=0
        )

        await loop.run_once()

        stored = await tmp_store.get_market_by_external_id("kalshi", "FUT-DISC-1")
        assert stored is not None
        assert stored.is_active is True

    async def test_null_end_date_stays_active(self, tmp_store):
        """Markets without end_date are not affected by expiry check."""
        no_end = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="NOEND-1",
            title="No End Date",
            yes_price=0.40,
        )
        adapter = FakeAdapter([no_end])
        loop = DiscoveryLoop(
            adapters=[adapter], store=tmp_store, interval_seconds=0
        )

        await loop.run_once()

        stored = await tmp_store.get_market_by_external_id("kalshi", "NOEND-1")
        assert stored is not None
        assert stored.is_active is True
