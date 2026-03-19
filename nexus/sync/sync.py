"""PostgreSQL-to-Convex sync layer (Phase 4, Milestone 4.1).

Reads from PostgreSQL materialized views and pushes precomputed
summaries to Convex tables. Supports both scheduled sync (markets,
summaries, topics) and event-driven sync (anomalies).
"""

import asyncio
import time
from typing import Any, Dict, List, Optional

from nexus.core.logging import LoggerMixin
from nexus.sync.convex_client import ConvexClient


class SyncLayer(LoggerMixin):
    """Orchestrates PostgreSQL → Convex data synchronization.

    Sync targets (from spec Section 8.4):
        markets          ← v_current_market_state    (every 30s)
        activeAnomalies  ← v_active_anomalies        (event-driven / 30s)
        trendingTopics   ← v_trending_topics          (every 5min)
        marketSummaries  ← v_market_summaries         (every 2min)
    """

    def __init__(
        self,
        store: Any,  # PostgresStore with view query methods
        convex: ConvexClient,
        market_interval: int = 30,
        summary_interval: int = 120,
        topics_interval: int = 300,
    ) -> None:
        self._store = store
        self._convex = convex
        self._market_interval = market_interval
        self._summary_interval = summary_interval
        self._topics_interval = topics_interval
        self._running = False
        self._last_cleanup: float = 0.0

    # ------------------------------------------------------------------
    # One-shot sync methods
    # ------------------------------------------------------------------

    # Max records per Convex mutation to stay under body size limits
    SYNC_BATCH_SIZE = 500

    async def sync_markets(self) -> int:
        """Push current market state to Convex. Returns record count.

        Only syncs markets that have received at least one event (price
        or volume) to avoid pushing 144K+ discovered-but-untracked markets.
        """
        rows = await self._store.query_market_state(with_events_only=True)
        if not rows:
            return 0

        records = [
            {
                "marketId": r["market_id"],
                "platform": r["platform"],
                "externalId": r["external_id"],
                "title": r["title"],
                "eventTitle": r.get("description") or "",
                "category": r.get("category") or "",
                "endDate": r.get("end_date"),
                "isActive": bool(r["is_active"]),
                "lastPrice": r.get("last_price"),
                "lastPriceTs": r.get("last_price_ts"),
                "lastVolume": r.get("last_volume"),
                "lastVolumeTs": r.get("last_volume_ts"),
                "syncedAt": int(time.time() * 1000),
            }
            for r in rows
        ]

        for i in range(0, len(records), self.SYNC_BATCH_SIZE):
            batch = records[i : i + self.SYNC_BATCH_SIZE]
            await self._convex.mutation(
                "nexusSync:upsertMarkets", {"markets": batch}
            )
        self.logger.info("sync_markets", count=len(records))

        # Periodically clean up stale Convex documents (every 5 min)
        now = time.time()
        if now - self._last_cleanup >= 300:
            valid_ids = [r["marketId"] for r in records]
            await self._cleanup_stale_markets(valid_ids)
            self._last_cleanup = now

        return len(records)

    async def _cleanup_stale_markets(self, valid_ids: List[int]) -> int:
        """Remove Convex nexusMarkets docs not in the valid set.

        Loops with batchSize=4000 until all records have been scanned,
        staying under Convex's 32K read limit per mutation.
        """
        total_deleted = 0
        batch_size = 4000

        while True:
            result = await self._convex.mutation(
                "nexusSync:cleanupStaleMarkets",
                {"validMarketIds": valid_ids, "batchSize": batch_size},
            )
            deleted = result.get("deleted", 0) if result else 0
            scanned = result.get("scanned", 0) if result else 0
            total_deleted += deleted

            if scanned < batch_size:
                break  # All records checked

        if total_deleted > 0:
            self.logger.info(
                "cleanup_stale_markets", deleted=total_deleted
            )
        return total_deleted

    async def sync_anomalies(self) -> int:
        """Push active anomalies to Convex. Returns record count."""
        rows = await self._store.query_active_anomalies()

        records = [
            {
                "anomalyId": r["anomaly_id"],
                "anomalyType": r["anomaly_type"],
                "severity": float(r["severity"]),
                "marketCount": r["market_count"],
                "detectedAt": r["detected_at"],
                "summary": r.get("summary") or "",
                "metadata": r.get("metadata") or "",
                "clusterName": r.get("cluster_name") or "",
                "syncedAt": int(time.time() * 1000),
            }
            for r in rows
        ]

        await self._convex.mutation(
            "nexusSync:upsertAnomalies", {"anomalies": records}
        )
        self.logger.info("sync_anomalies", count=len(records))
        return len(records)

    async def sync_trending_topics(self) -> int:
        """Push trending topics to Convex. Returns record count."""
        rows = await self._store.query_trending_topics()
        if not rows:
            return 0

        records = [
            {
                "clusterId": r["cluster_id"],
                "name": r["name"],
                "description": r.get("description") or "",
                "marketCount": r["market_count"],
                "anomalyCount": r["anomaly_count"],
                "maxSeverity": float(r["max_severity"]) if r.get("max_severity") else 0.0,
                "syncedAt": int(time.time() * 1000),
            }
            for r in rows
        ]

        await self._convex.mutation(
            "nexusSync:upsertTrendingTopics", {"topics": records}
        )
        self.logger.info("sync_trending_topics", count=len(records))
        return len(records)

    async def sync_market_summaries(self) -> int:
        """Push market summaries to Convex. Returns record count."""
        rows = await self._store.query_market_summaries()
        if not rows:
            return 0

        records = [
            {
                "marketId": r["market_id"],
                "platform": r["platform"],
                "title": r["title"],
                "category": r.get("category") or "",
                "eventCount": r["event_count"],
                "firstEventTs": r.get("first_event_ts"),
                "lastEventTs": r.get("last_event_ts"),
                "syncedAt": int(time.time() * 1000),
            }
            for r in rows
        ]

        for i in range(0, len(records), self.SYNC_BATCH_SIZE):
            batch = records[i : i + self.SYNC_BATCH_SIZE]
            await self._convex.mutation(
                "nexusSync:upsertMarketSummaries", {"summaries": batch}
            )
        self.logger.info("sync_market_summaries", count=len(records))
        return len(records)

    async def sync_all(self) -> Dict[str, int]:
        """Run all sync operations once. Returns counts per target."""
        # Refresh views before syncing
        if hasattr(self._store, "refresh_views"):
            await self._store.refresh_views()

        results = {}
        results["markets"] = await self.sync_markets()
        results["anomalies"] = await self.sync_anomalies()
        results["trending_topics"] = await self.sync_trending_topics()
        results["market_summaries"] = await self.sync_market_summaries()

        self.logger.info("sync_all_complete", **results)
        return results

    # ------------------------------------------------------------------
    # Continuous sync loop
    # ------------------------------------------------------------------

    async def run_forever(self) -> None:
        """Run scheduled sync loops at configured intervals.

        Markets sync every market_interval seconds.
        Anomalies sync alongside markets (event-driven priority).
        Summaries sync every summary_interval seconds.
        Topics sync every topics_interval seconds.
        """
        self._running = True

        last_market = 0.0
        last_summary = 0.0
        last_topics = 0.0
        last_market_view = 0.0

        while self._running:
            now = time.time()

            try:
                # Markets + anomalies (highest frequency)
                if now - last_market >= self._market_interval:
                    if hasattr(self._store, "refresh_view"):
                        # v_active_anomalies is small — refresh every cycle
                        await self._store.refresh_view("v_active_anomalies")
                        # v_current_market_state is heavy — refresh every 5 min
                        if now - last_market_view >= 300:
                            await self._store.refresh_view("v_current_market_state")
                            last_market_view = now
                    await self.sync_markets()
                    await self.sync_anomalies()
                    last_market = now

                # Market summaries (every 30 min by default)
                if now - last_summary >= self._summary_interval:
                    if hasattr(self._store, "refresh_view"):
                        await self._store.refresh_view("v_market_summaries")
                    await self.sync_market_summaries()
                    last_summary = now

                # Trending topics
                if now - last_topics >= self._topics_interval:
                    if hasattr(self._store, "refresh_view"):
                        await self._store.refresh_view("v_trending_topics")
                    await self.sync_trending_topics()
                    last_topics = now

            except Exception:
                self.logger.exception("sync_cycle_error")

            await asyncio.sleep(5)  # Check every 5 seconds

    async def stop(self) -> None:
        """Stop the sync loop."""
        self._running = False
