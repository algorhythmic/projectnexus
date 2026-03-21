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
        self._dynamic_update_calls: List[dict] = []
        self._dynamic_update_result: bool = True

    async def discover(self) -> List[DiscoveredMarket]:
        return self._markets

    async def connect(self, tickers: Sequence[str]) -> AsyncIterator[EventRecord]:
        for event in self._events:
            yield event

    async def update_market_subscriptions(
        self,
        add_tickers=None,
        remove_tickers=None,
    ) -> bool:
        self._dynamic_update_calls.append({
            "add": list(add_tickers) if add_tickers else [],
            "remove": list(remove_tickers) if remove_tickers else [],
        })
        return self._dynamic_update_result


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

        manager = IngestionManager([adapter], tmp_store, bus, sample_settings)

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

        manager = IngestionManager([adapter], tmp_store, bus, sample_settings)

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
        manager = IngestionManager([adapter], tmp_store, bus, sample_settings)

        await manager._build_ticker_cache()
        assert "CACHED-1" in manager._ticker_to_market_id

    async def test_stop_sets_running_false(self, tmp_store, sample_settings):
        """stop() sets _running to False."""
        adapter = FakeStreamingAdapter(markets=[], events=[])
        bus = EventBus(tmp_store, max_size=100, batch_size=10, batch_timeout=0.1)
        manager = IngestionManager([adapter], tmp_store, bus, sample_settings)
        manager._running = True
        await manager.stop()
        assert manager._running is False

    async def test_terminal_status_change_deactivates_market(
        self, tmp_store, sample_settings
    ):
        """STATUS_CHANGE with terminal status deactivates the market."""
        market = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="TERM-1",
            title="Terminal Status Test",
            yes_price=0.5,
        )
        await tmp_store.upsert_markets([market])
        stored = await tmp_store.get_market_by_external_id("kalshi", "TERM-1")
        assert stored is not None and stored.id is not None

        adapter = FakeStreamingAdapter(markets=[], events=[])
        bus = EventBus(tmp_store, max_size=100, batch_size=10, batch_timeout=0.1)
        manager = IngestionManager([adapter], tmp_store, bus, sample_settings)
        await manager._build_ticker_cache()

        # Simulate a terminal STATUS_CHANGE event
        event = EventRecord(
            market_id=stored.id,
            event_type=EventType.STATUS_CHANGE,
            new_value=0.0,
            metadata=json.dumps({"ticker": "TERM-1", "status": "closed"}),
            timestamp=1000000,
        )
        await manager._handle_status_change(event)

        # Market should be deactivated
        updated = await tmp_store.get_market_by_id(stored.id)
        assert updated is not None
        assert updated.is_active is False

        # Ticker should be removed from cache
        assert "TERM-1" not in manager._ticker_to_market_id

    async def test_non_terminal_status_change_keeps_market_active(
        self, tmp_store, sample_settings
    ):
        """STATUS_CHANGE with non-terminal status does NOT deactivate."""
        market = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="NONTERM-1",
            title="Non-Terminal Test",
            yes_price=0.5,
        )
        await tmp_store.upsert_markets([market])
        stored = await tmp_store.get_market_by_external_id("kalshi", "NONTERM-1")
        assert stored is not None and stored.id is not None

        adapter = FakeStreamingAdapter(markets=[], events=[])
        bus = EventBus(tmp_store, max_size=100, batch_size=10, batch_timeout=0.1)
        manager = IngestionManager([adapter], tmp_store, bus, sample_settings)
        await manager._build_ticker_cache()

        # Non-terminal status (e.g. "active") should NOT deactivate
        event = EventRecord(
            market_id=stored.id,
            event_type=EventType.STATUS_CHANGE,
            new_value=0.0,
            metadata=json.dumps({"ticker": "NONTERM-1", "status": "active"}),
            timestamp=1000000,
        )
        await manager._handle_status_change(event)

        updated = await tmp_store.get_market_by_id(stored.id)
        assert updated is not None
        assert updated.is_active is True

        # Ticker should still be in cache
        assert "NONTERM-1" in manager._ticker_to_market_id

    async def test_handle_status_change_all_terminal_statuses(
        self, tmp_store, sample_settings
    ):
        """All terminal statuses (closed, determined, finalized, settled) deactivate."""
        for i, status in enumerate(["closed", "determined", "finalized", "settled"]):
            ext_id = f"ALLTERM-{i}"
            market = DiscoveredMarket(
                platform=Platform.KALSHI,
                external_id=ext_id,
                title=f"Terminal {status}",
                yes_price=0.5,
            )
            await tmp_store.upsert_markets([market])
            stored = await tmp_store.get_market_by_external_id("kalshi", ext_id)
            assert stored is not None and stored.id is not None

            adapter = FakeStreamingAdapter(markets=[], events=[])
            bus = EventBus(tmp_store, max_size=100, batch_size=10, batch_timeout=0.1)
            manager = IngestionManager([adapter], tmp_store, bus, sample_settings)
            await manager._build_ticker_cache()

            event = EventRecord(
                market_id=stored.id,
                event_type=EventType.STATUS_CHANGE,
                new_value=0.0,
                metadata=json.dumps({"ticker": ext_id, "status": status}),
                timestamp=1000000,
            )
            await manager._handle_status_change(event)

            updated = await tmp_store.get_market_by_id(stored.id)
            assert updated is not None
            assert updated.is_active is False, f"Status '{status}' should deactivate"

    async def test_try_dynamic_resubscribe_success(self, tmp_store, sample_settings):
        """_try_dynamic_resubscribe adds new tickers via adapter."""
        market1 = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="DYN-1",
            title="Dynamic Test 1",
            yes_price=0.5,
        )
        market2 = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="DYN-2",
            title="Dynamic Test 2",
            yes_price=0.6,
        )
        await tmp_store.upsert_markets([market1, market2])

        adapter = FakeStreamingAdapter(markets=[], events=[])
        bus = EventBus(tmp_store, max_size=100, batch_size=10, batch_timeout=0.1)
        manager = IngestionManager([adapter], tmp_store, bus, sample_settings)
        await manager._build_ticker_cache()

        # Simulate: currently subscribed to DYN-1 only
        manager._subscribed_tickers = {"DYN-1"}

        result = await manager._try_dynamic_resubscribe(adapter)

        assert result is True
        assert len(adapter._dynamic_update_calls) == 1
        call = adapter._dynamic_update_calls[0]
        assert "DYN-2" in call["add"]
        assert "DYN-1" in manager._subscribed_tickers
        assert "DYN-2" in manager._subscribed_tickers

    async def test_try_dynamic_resubscribe_failure_returns_false(
        self, tmp_store, sample_settings
    ):
        """_try_dynamic_resubscribe returns False when adapter fails."""
        market = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="FAIL-DYN",
            title="Fail Dynamic Test",
            yes_price=0.5,
        )
        await tmp_store.upsert_markets([market])

        adapter = FakeStreamingAdapter(markets=[], events=[])
        adapter._dynamic_update_result = False  # Simulate failure
        bus = EventBus(tmp_store, max_size=100, batch_size=10, batch_timeout=0.1)
        manager = IngestionManager([adapter], tmp_store, bus, sample_settings)
        await manager._build_ticker_cache()

        manager._subscribed_tickers = set()  # Nothing subscribed yet

        result = await manager._try_dynamic_resubscribe(adapter)

        assert result is False

    async def test_try_dynamic_resubscribe_no_changes(
        self, tmp_store, sample_settings
    ):
        """_try_dynamic_resubscribe with no changes returns True without calling adapter."""
        market = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="SAME-1",
            title="Same Test",
            yes_price=0.5,
        )
        await tmp_store.upsert_markets([market])

        adapter = FakeStreamingAdapter(markets=[], events=[])
        bus = EventBus(tmp_store, max_size=100, batch_size=10, batch_timeout=0.1)
        manager = IngestionManager([adapter], tmp_store, bus, sample_settings)
        await manager._build_ticker_cache()

        # Already subscribed to everything
        manager._subscribed_tickers = set(manager._ticker_to_market_id.keys())

        result = await manager._try_dynamic_resubscribe(adapter)

        assert result is True
        assert len(adapter._dynamic_update_calls) == 0

    async def test_event_lifecycle_triggers_resubscribe(
        self, tmp_store, sample_settings
    ):
        """Event lifecycle v2 'event_created' sets _resubscribe_needed."""
        adapter = FakeStreamingAdapter(markets=[], events=[])
        bus = EventBus(tmp_store, max_size=100, batch_size=10, batch_timeout=0.1)
        manager = IngestionManager([adapter], tmp_store, bus, sample_settings)

        # Simulate an event_lifecycle STATUS_CHANGE from the v2 channel
        event = EventRecord(
            market_id=0,
            event_type=EventType.STATUS_CHANGE,
            new_value=0.0,
            metadata=json.dumps({
                "event_ticker": "NEW-EVENT-123",
                "lifecycle_type": "event_created",
                "source": "event_lifecycle_v2",
            }),
            timestamp=1000000,
        )
        await manager._handle_status_change(event)

        assert manager._resubscribe_needed.is_set()

    async def test_terminal_status_removes_from_subscribed_tickers(
        self, tmp_store, sample_settings
    ):
        """Terminal status change also removes ticker from _subscribed_tickers."""
        market = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="DEACTIVATE-SUB",
            title="Deactivate Sub Test",
            yes_price=0.5,
        )
        await tmp_store.upsert_markets([market])
        stored = await tmp_store.get_market_by_external_id("kalshi", "DEACTIVATE-SUB")
        assert stored is not None and stored.id is not None

        adapter = FakeStreamingAdapter(markets=[], events=[])
        bus = EventBus(tmp_store, max_size=100, batch_size=10, batch_timeout=0.1)
        manager = IngestionManager([adapter], tmp_store, bus, sample_settings)
        await manager._build_ticker_cache()
        manager._subscribed_tickers = {"DEACTIVATE-SUB"}

        event = EventRecord(
            market_id=stored.id,
            event_type=EventType.STATUS_CHANGE,
            new_value=0.0,
            metadata=json.dumps({"ticker": "DEACTIVATE-SUB", "status": "settled"}),
            timestamp=1000000,
        )
        await manager._handle_status_change(event)

        assert "DEACTIVATE-SUB" not in manager._subscribed_tickers
        assert "DEACTIVATE-SUB" not in manager._ticker_to_market_id
