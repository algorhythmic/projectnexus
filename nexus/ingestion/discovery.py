"""Market discovery polling loop.

Periodically calls each adapter's discover() method, upserts results
into the store, and emits events for newly seen markets and price changes.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from nexus.adapters.base import BaseAdapter
from nexus.core.logging import LoggerMixin
from nexus.core.types import DiscoveredMarket, EventRecord, EventType
from nexus.store.base import BaseStore


class DiscoveryLoop(LoggerMixin):
    """Polls platform adapters on a configurable interval.

    On each cycle:
      1. Call adapter.discover() for each registered adapter.
      2. Upsert discovered markets into the store.
      3. For newly seen markets, insert a ``new_market`` event.
      4. For markets whose yes_price changed, insert a ``price_change`` event.
      5. Sleep for the configured interval.
    """

    def __init__(
        self,
        adapters: List[BaseAdapter],
        store: BaseStore,
        interval_seconds: int = 60,
        staleness_hours: int = 6,
    ) -> None:
        self.adapters = adapters
        self.store = store
        self.interval = interval_seconds
        self._staleness_ms = staleness_hours * 3600 * 1000
        self._running = False
        # In-memory price cache: (platform, external_id) -> last known yes_price
        self._price_cache: Dict[Tuple[str, str], Optional[float]] = {}

    async def run_forever(self) -> None:
        """Main polling loop.  Runs until stop() is called."""
        self._running = True
        self.logger.info(
            "Discovery loop started", interval=self.interval
        )
        while self._running:
            await self.run_once()
            await asyncio.sleep(self.interval)

    async def run_once(self) -> Dict[str, int]:
        """Execute a single discovery cycle across all adapters.

        Returns a dict with ``discovered`` and ``new`` counts per adapter.
        """
        results: Dict[str, int] = {}

        for adapter in self.adapters:
            name = adapter.__class__.__name__
            try:
                discovered = await adapter.discover()
                new_count = await self.store.upsert_markets(discovered)

                # Deactivate markets not updated within the staleness window
                now_ms = int(time.time() * 1000)
                platform = (
                    discovered[0].platform.value if discovered else None
                )
                deactivated = 0
                if platform and self._staleness_ms > 0:
                    cutoff_ms = now_ms - self._staleness_ms
                    deactivated = (
                        await self.store.deactivate_stale_markets(
                            platform, cutoff_ms
                        )
                    )

                events: List[EventRecord] = []
                if self._price_cache:
                    events = await self._generate_events(discovered)
                else:
                    # First cycle: seed cache AND emit price events
                    events = await self._seed_with_events(discovered)
                if events:
                    await self.store.insert_events(events)
                results[name] = new_count
                self.logger.info(
                    "Discovery cycle complete",
                    adapter=name,
                    discovered=len(discovered),
                    new=new_count,
                    deactivated=deactivated,
                    events_emitted=len(events),
                )
            except Exception as exc:
                self.logger.error(
                    "Discovery cycle failed",
                    adapter=name,
                    error=str(exc),
                )
                results[name] = 0

        # Check for markets past their end_date (catches resolutions
        # missed during WebSocket disconnects or restarts)
        await self._check_end_date_expiry()

        return results

    async def stop(self) -> None:
        """Signal the loop to stop after the current cycle."""
        self._running = False
        self.logger.info("Discovery loop stopping")

    # ------------------------------------------------------------------
    # Event generation
    # ------------------------------------------------------------------

    async def _generate_events(
        self, markets: List[DiscoveredMarket]
    ) -> List[EventRecord]:
        """Compare discovered markets to stored state and emit events."""
        events: List[EventRecord] = []
        if not markets:
            return events

        now_ms = int(time.time() * 1000)

        # Batch-load all stored markets for this platform (single query
        # instead of N individual lookups)
        platform = markets[0].platform.value
        stored_markets = await self.store.get_active_markets(platform=platform)
        stored_lookup: Dict[Tuple[str, str], int] = {
            (m.platform.value, m.external_id): m.id
            for m in stored_markets
            if m.id is not None
        }

        for m in markets:
            market_key = (m.platform.value, m.external_id)
            market_id = stored_lookup.get(market_key)
            if market_id is None:
                # Market not yet in store -- skip event generation;
                # it will be created by the upsert and picked up next cycle.
                continue

            old_price = self._price_cache.get(market_key)

            if old_price is None:
                # First time seeing this market in this session — treat as new
                if m.yes_price is not None:
                    events.append(
                        EventRecord(
                            market_id=market_id,
                            event_type=EventType.NEW_MARKET,
                            old_value=None,
                            new_value=m.yes_price,
                            metadata=json.dumps(
                                {"title": m.title, "category": m.category}
                            ),
                            timestamp=now_ms,
                        )
                    )
                    # Also emit price_change so the materialized view
                    # (v_current_market_state) picks up this price
                    events.append(
                        EventRecord(
                            market_id=market_id,
                            event_type=EventType.PRICE_CHANGE,
                            old_value=None,
                            new_value=m.yes_price,
                            metadata=json.dumps({"source": "first_seen"}),
                            timestamp=now_ms,
                        )
                    )
            elif m.yes_price is not None and m.yes_price != old_price:
                events.append(
                    EventRecord(
                        market_id=market_id,
                        event_type=EventType.PRICE_CHANGE,
                        old_value=old_price,
                        new_value=m.yes_price,
                        metadata=None,
                        timestamp=now_ms,
                    )
                )

            # Update the cache
            self._price_cache[market_key] = m.yes_price

        return events

    async def _check_end_date_expiry(self) -> int:
        """Deactivate active markets whose end_date has passed."""
        now_iso = datetime.now(timezone.utc).isoformat()
        expired = await self.store.deactivate_expired_markets(now_iso)
        if expired > 0:
            self.logger.info(
                "Deactivated expired markets by end_date",
                count=expired,
            )
        return expired

    async def _seed_with_events(
        self, markets: List[DiscoveredMarket]
    ) -> List[EventRecord]:
        """Seed the price cache AND emit price_change events.

        On the very first discovery cycle the cache is empty.  Previously
        we silently seeded the cache, which meant the materialized view
        (``v_current_market_state``) never saw prices for markets that
        existed before the process started.
        """
        events: List[EventRecord] = []
        if not markets:
            return events

        now_ms = int(time.time() * 1000)

        # Batch-load stored markets (same pattern as _generate_events)
        platform = markets[0].platform.value
        stored_markets = await self.store.get_active_markets(platform=platform)
        stored_lookup: Dict[Tuple[str, str], int] = {
            (m.platform.value, m.external_id): m.id
            for m in stored_markets
            if m.id is not None
        }

        for m in markets:
            cache_key = (m.platform.value, m.external_id)
            # Always seed the cache
            self._price_cache[cache_key] = m.yes_price

            # Emit price_change for markets already in DB with a price
            if m.yes_price is not None:
                market_id = stored_lookup.get(cache_key)
                if market_id is not None:
                    events.append(
                        EventRecord(
                            market_id=market_id,
                            event_type=EventType.PRICE_CHANGE,
                            old_value=None,
                            new_value=m.yes_price,
                            metadata=json.dumps(
                                {
                                    "source": "discovery_seed",
                                    "title": m.title,
                                }
                            ),
                            timestamp=now_ms,
                        )
                    )

        return events
