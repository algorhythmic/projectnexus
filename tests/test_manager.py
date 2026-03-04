"""Tests for the IngestionManager."""

import asyncio
import json
from typing import AsyncIterator, List, Sequence

import pytest

from nexus.adapters.base import BaseAdapter
from nexus.core.config import Settings
from nexus.core.types import (
    DiscoveredMarket,
    EventRecord,
    EventType,
    Platform,
)
from nexus.ingestion.bus import EventBus
from nexus.ingestion.manager import IngestionManager


class FakeStreamingAdapter(BaseAdapter):
    """Adapter that returns canned discovery data and streams fake events."""

    def __init__(
        self,
        markets: List[DiscoveredMarket],
        events: List[EventRecord],
    ) -> None:
        super().__init__(base_url="https://fake.api", rate_limit=100.0)
        self._markets = markets
        self._events = events

    async def discover(self) -> List[DiscoveredMarket]:
        return self._markets

    async def connect(self, tickers: Sequence[str]) -> AsyncIterator[EventRecord]:
        for event in self._events:
            yield event


class TestIngestionManager:
    @pytest.fixture
    def sample_settings(self):
        return Settings(
            kalshi_api_key="",
            kalshi_private_key_path="",
            discovery_interval_seconds=1,
            ws_reconnect_delay=0.1,
            event_queue_max_size=100,
            event_batch_size=10,
            event_batch_timeout=0.1,
        )

    async def test_ticker_resolution(self, tmp_store, sample_settings):
        """Manager resolves ticker in event metadata to market_id."""
        # Set up a market in the store
        market = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="RESOLVE-ME",
            title="Resolution Test",
            yes_price=0.5,
        )
        await tmp_store.upsert_markets([market])
        stored = await tmp_store.get_market_by_external_id("kalshi", "RESOLVE-ME")
        assert stored is not None

        # Create a WS event with market_id=0 and ticker in metadata
        ws_event = EventRecord(
            market_id=0,
            event_type=EventType.PRICE_CHANGE,
            new_value=0.65,
            metadata=json.dumps({"ticker": "RESOLVE-ME"}),
            timestamp=1000000,
        )

        adapter = FakeStreamingAdapter(markets=[market], events=[ws_event])
        bus = EventBus(
            tmp_store,
            max_size=sample_settings.event_queue_max_size,
            batch_size=sample_settings.event_batch_size,
            batch_timeout=sample_settings.event_batch_timeout,
        )
        bus.start()

        manager = IngestionManager(adapter, tmp_store, bus, sample_settings)

        # Run briefly then stop
        async def run_briefly():
            task = asyncio.create_task(manager.run())
            await asyncio.sleep(4.0)
            await manager.stop()
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        await run_briefly()
        await bus.stop()

        # Event should be in the store with the real market_id
        events = await tmp_store.get_events(market_id=stored.id)
        ws_events = [e for e in events if e.event_type == EventType.PRICE_CHANGE]
        assert len(ws_events) >= 1
        assert ws_events[0].market_id == stored.id

    async def test_unresolved_ticker_skipped(self, tmp_store, sample_settings):
        """Events with unknown tickers are skipped."""
        ws_event = EventRecord(
            market_id=0,
            event_type=EventType.TRADE,
            new_value=0.5,
            metadata=json.dumps({"ticker": "UNKNOWN-TICKER"}),
            timestamp=1000000,
        )

        adapter = FakeStreamingAdapter(markets=[], events=[ws_event])
        bus = EventBus(
            tmp_store,
            max_size=100,
            batch_size=10,
            batch_timeout=0.1,
        )

        manager = IngestionManager(adapter, tmp_store, bus, sample_settings)

        # Build cache with no markets
        await manager._build_ticker_cache()
        resolved = manager._resolve_event(ws_event)
        assert resolved is None

    async def test_extract_ticker_from_metadata(self, tmp_store, sample_settings):
        """_extract_ticker parses ticker from JSON metadata."""
        event = EventRecord(
            market_id=0,
            event_type=EventType.PRICE_CHANGE,
            new_value=0.5,
            metadata=json.dumps({"ticker": "MY-TICKER", "extra": "data"}),
            timestamp=1000000,
        )
        ticker = IngestionManager._extract_ticker(event)
        assert ticker == "MY-TICKER"

    async def test_extract_ticker_no_metadata(self, tmp_store, sample_settings):
        """_extract_ticker returns None when metadata is None."""
        event = EventRecord(
            market_id=0,
            event_type=EventType.PRICE_CHANGE,
            new_value=0.5,
            metadata=None,
            timestamp=1000000,
        )
        ticker = IngestionManager._extract_ticker(event)
        assert ticker is None

    async def test_build_ticker_cache(self, tmp_store, sample_settings):
        """_build_ticker_cache populates from store."""
        market = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="CACHED-1",
            title="Cache Test",
            yes_price=0.5,
        )
        await tmp_store.upsert_markets([market])

        adapter = FakeStreamingAdapter(markets=[], events=[])
        bus = EventBus(tmp_store, max_size=100, batch_size=10, batch_timeout=0.1)
        manager = IngestionManager(adapter, tmp_store, bus, sample_settings)

        await manager._build_ticker_cache()
        assert "CACHED-1" in manager._ticker_to_market_id

    async def test_stop_sets_running_false(self, tmp_store, sample_settings):
        """stop() sets _running to False."""
        adapter = FakeStreamingAdapter(markets=[], events=[])
        bus = EventBus(tmp_store, max_size=100, batch_size=10, batch_timeout=0.1)
        manager = IngestionManager(adapter, tmp_store, bus, sample_settings)
        manager._running = True
        await manager.stop()
        assert manager._running is False
