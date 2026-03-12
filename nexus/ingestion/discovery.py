"""Market discovery polling loop.

Periodically calls each adapter's discover() method, upserts results
into the store, and emits events for newly seen markets and price changes.
"""

import asyncio
import json
import time
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
    ) -> None:
        self.adapters = adapters
        self.store = store
        self.interval = interval_seconds
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
                # Skip event generation on first cycle (empty cache)
                # to avoid N+1 queries for thousands of new markets
                events: List[EventRecord] = []
                if self._price_cache:
                    events = await self._generate_events(discovered)
                    if events:
                        await self.store.insert_events(events)
                else:
                    # Seed the price cache without generating events
                    for m in discovered:
                        cache_key = (m.platform.value, m.external_id)
                        self._price_cache[cache_key] = m.yes_price
                results[name] = new_count
                self.logger.info(
                    "Discovery cycle complete",
                    adapter=name,
                    discovered=len(discovered),
                    new=new_count,
                    events_emitted=len(events),
                )
            except Exception as exc:
                self.logger.error(
                    "Discovery cycle failed",
                    adapter=name,
                    error=str(exc),
                )
                results[name] = 0
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
        now_ms = int(time.time() * 1000)

        for m in markets:
            stored = await self.store.get_market_by_external_id(
                m.platform.value, m.external_id
            )
            if stored is None or stored.id is None:
                # Market not yet in store -- skip event generation;
                # it will be created by the upsert and picked up next cycle.
                continue

            cache_key = (m.platform.value, m.external_id)
            old_price = self._price_cache.get(cache_key)

            if old_price is None:
                # First time seeing this market in this session — treat as new
                if m.yes_price is not None:
                    events.append(
                        EventRecord(
                            market_id=stored.id,
                            event_type=EventType.NEW_MARKET,
                            old_value=None,
                            new_value=m.yes_price,
                            metadata=json.dumps(
                                {"title": m.title, "category": m.category}
                            ),
                            timestamp=now_ms,
                        )
                    )
            elif m.yes_price is not None and m.yes_price != old_price:
                events.append(
                    EventRecord(
                        market_id=stored.id,
                        event_type=EventType.PRICE_CHANGE,
                        old_value=old_price,
                        new_value=m.yes_price,
                        metadata=None,
                        timestamp=now_ms,
                    )
                )

            # Update the cache
            self._price_cache[cache_key] = m.yes_price

        return events
