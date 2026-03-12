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

        # First cycle: upsert + new_market event
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
        # First cycle seeds the price cache (no events generated).
        # Second cycle detects the price change.
        event_types = {e.event_type.value for e in events}
        assert "price_change" in event_types

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
