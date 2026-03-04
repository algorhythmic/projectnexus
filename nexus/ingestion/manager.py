"""Ingestion manager — orchestrates discovery + WebSocket streaming.

Runs the DiscoveryLoop and adapter.connect() concurrently via
asyncio.TaskGroup.  Resolves market tickers from WebSocket events to
database IDs before routing them to the EventBus.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from nexus.adapters.base import BaseAdapter
from nexus.core.config import Settings
from nexus.core.logging import LoggerMixin
from nexus.core.types import EventRecord
from nexus.ingestion.bus import EventBus
from nexus.ingestion.discovery import DiscoveryLoop
from nexus.store.base import BaseStore

if TYPE_CHECKING:
    from nexus.ingestion.metrics import MetricsCollector


class IngestionManager(LoggerMixin):
    """Orchestrator that runs REST discovery and WebSocket streaming
    concurrently, resolving tickers to market IDs and routing events
    through the EventBus.

    Usage::

        manager = IngestionManager(adapter, store, bus, settings)
        await manager.run()   # blocks until stop() or error
    """

    def __init__(
        self,
        adapters: List[BaseAdapter],
        store: BaseStore,
        bus: EventBus,
        settings: Settings,
        metrics: Optional[MetricsCollector] = None,
    ) -> None:
        self._adapters = adapters
        self._store = store
        self._bus = bus
        self._settings = settings
        self._metrics = metrics
        self._running = False

        # ticker string → database market.id
        self._ticker_to_market_id: Dict[str, int] = {}
        # Tickers currently subscribed via WebSocket
        self._subscribed_tickers: Set[str] = set()

    async def run(self) -> None:
        """Start discovery + streaming concurrently.

        Uses asyncio.TaskGroup for structured concurrency: if either
        task fails, the other is cancelled automatically.
        """
        self._running = True

        # Build initial ticker cache from existing markets in the store
        await self._build_ticker_cache()
        self.logger.info(
            "IngestionManager starting",
            cached_tickers=len(self._ticker_to_market_id),
            adapters=len(self._adapters),
        )

        # Start health reporter if metrics are available
        health_reporter = None
        if self._metrics is not None:
            from nexus.ingestion.health import HealthReporter

            health_reporter = HealthReporter(
                self._metrics,
                interval_seconds=self._settings.health_report_interval_seconds,
            )
            health_reporter.start()

        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._discovery_task())
                for adapter in self._adapters:
                    tg.create_task(self._streaming_task(adapter))
        except* Exception as eg:
            for exc in eg.exceptions:
                if not isinstance(exc, asyncio.CancelledError):
                    self.logger.error(
                        "IngestionManager task failed",
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
        finally:
            if health_reporter is not None:
                await health_reporter.stop()

    async def stop(self) -> None:
        """Signal all tasks to stop."""
        self._running = False
        self.logger.info("IngestionManager stopping")

    # ------------------------------------------------------------------
    # Ticker cache
    # ------------------------------------------------------------------

    async def _build_ticker_cache(self) -> None:
        """Populate the ticker→market_id cache from the store."""
        markets = await self._store.get_active_markets()
        for m in markets:
            if m.id is not None:
                self._ticker_to_market_id[m.external_id] = m.id

    async def _refresh_ticker_cache(self) -> List[str]:
        """Refresh the cache and return any newly discovered tickers."""
        old_tickers = set(self._ticker_to_market_id.keys())
        await self._build_ticker_cache()
        new_tickers = set(self._ticker_to_market_id.keys()) - old_tickers
        return list(new_tickers)

    # ------------------------------------------------------------------
    # Discovery task
    # ------------------------------------------------------------------

    async def _discovery_task(self) -> None:
        """Run the REST discovery loop."""
        discovery = DiscoveryLoop(
            adapters=self._adapters,
            store=self._store,
            interval_seconds=self._settings.discovery_interval_seconds,
        )

        while self._running:
            try:
                results = await discovery.run_once()
                # Refresh ticker cache after discovery
                new_tickers = await self._refresh_ticker_cache()
                if new_tickers:
                    self.logger.info(
                        "New tickers discovered",
                        count=len(new_tickers),
                        tickers=new_tickers[:10],
                    )
            except Exception as exc:
                self.logger.error(
                    "Discovery cycle error",
                    error=str(exc),
                )
                if self._metrics is not None:
                    from nexus.ingestion.metrics import ErrorCategory

                    self._metrics.record_error(ErrorCategory.DISCOVERY_ERROR)

            await asyncio.sleep(self._settings.discovery_interval_seconds)

    # ------------------------------------------------------------------
    # Streaming task
    # ------------------------------------------------------------------

    async def _streaming_task(self, adapter: BaseAdapter) -> None:
        """Run the WebSocket streaming loop for a specific adapter."""
        adapter_name = adapter.__class__.__name__
        # Wait briefly for the first discovery cycle to populate tickers
        await asyncio.sleep(2.0)

        while self._running:
            tickers = list(self._ticker_to_market_id.keys())
            if not tickers:
                self.logger.info(
                    "No tickers to subscribe — waiting for discovery",
                    adapter=adapter_name,
                )
                await asyncio.sleep(self._settings.discovery_interval_seconds)
                continue

            # Limit to max subscriptions
            max_subs = self._settings.ws_max_subscriptions
            subscribe_tickers = tickers[:max_subs]
            self._subscribed_tickers = set(subscribe_tickers)

            self.logger.info(
                "Starting WebSocket stream",
                adapter=adapter_name,
                tickers=len(subscribe_tickers),
            )

            try:
                if self._metrics is not None:
                    self._metrics.record_ws_connected()

                async for event in adapter.connect(subscribe_tickers):
                    if not self._running:
                        break
                    resolved = self._resolve_event(event)
                    if resolved is not None:
                        await self._bus.put(resolved)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._metrics is not None:
                    from nexus.ingestion.metrics import ErrorCategory

                    self._metrics.record_ws_disconnected()
                    self._metrics.record_error(ErrorCategory.WS_ERROR)
                self.logger.error(
                    "Streaming error",
                    adapter=adapter_name,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                # The adapter's connect() handles reconnection internally,
                # but if it fails completely we log and retry
                await asyncio.sleep(self._settings.ws_reconnect_delay)

    # ------------------------------------------------------------------
    # Event resolution
    # ------------------------------------------------------------------

    def _resolve_event(self, event: EventRecord) -> Optional[EventRecord]:
        """Resolve market_id=0 events to real database IDs.

        Returns None if the ticker can't be resolved (will be picked
        up after the next discovery cycle).
        """
        if event.market_id != 0:
            return event

        # Extract ticker from metadata
        ticker = self._extract_ticker(event)
        if ticker is None:
            return None

        market_id = self._ticker_to_market_id.get(ticker)
        if market_id is None:
            self.logger.debug(
                "Unresolved ticker — skipping event",
                ticker=ticker,
                event_type=event.event_type.value,
            )
            return None

        return EventRecord(
            market_id=market_id,
            event_type=event.event_type,
            old_value=event.old_value,
            new_value=event.new_value,
            metadata=event.metadata,
            timestamp=event.timestamp,
        )

    @staticmethod
    def _extract_ticker(event: EventRecord) -> Optional[str]:
        """Extract the market ticker from event metadata JSON."""
        if not event.metadata:
            return None
        try:
            data = json.loads(event.metadata)
            return data.get("ticker")
        except (json.JSONDecodeError, TypeError):
            return None
