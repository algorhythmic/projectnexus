"""PostgreSQL data refresh and sync layer.

Reads from PostgreSQL materialized views and:
  1. Populates an in-memory BroadcastCache for the REST API (primary)
  2. Optionally pushes to Convex tables (legacy, transition period)
"""

import asyncio
import time
from typing import Any, Dict, List, Optional

from nexus.api.cache import BroadcastCache
from nexus.core.logging import LoggerMixin
from nexus.sync.convex_client import ConvexClient


class SyncLayer(LoggerMixin):
    """Orchestrates PostgreSQL → BroadcastCache (+ optional Convex) sync.

    Sync targets:
        markets          ← v_current_market_state    (every 60s)
        activeAnomalies  ← v_active_anomalies        (every 60s)
        trendingTopics   ← v_trending_topics          (every 10min)
        marketSummaries  ← v_market_summaries         (every 5min)

    If a ``health_tracker`` is provided, the market sync merges in
    computed health scores from the in-memory intelligence engine.
    """

    def __init__(
        self,
        store: Any,  # PostgresStore with view query methods
        convex: Optional[ConvexClient] = None,
        cache: Optional[BroadcastCache] = None,
        market_interval: int = 60,
        summary_interval: int = 300,
        topics_interval: int = 600,
        health_tracker: Any = None,  # MarketHealthTracker
    ) -> None:
        self._store = store
        self._convex = convex
        self._cache = cache
        self._market_interval = market_interval
        self._summary_interval = summary_interval
        self._topics_interval = topics_interval
        self._health_tracker = health_tracker
        self._running = False
        self._last_cleanup: float = 0.0

    # ------------------------------------------------------------------
    # One-shot sync methods
    # ------------------------------------------------------------------

    # Max records per Convex mutation to stay under body size limits
    SYNC_BATCH_SIZE = 500

    async def sync_markets(self) -> int:
        """Refresh market data into cache (+ optional Convex). Returns count.

        Only syncs markets that have received at least one event (price
        or volume) to avoid pushing 144K+ discovered-but-untracked markets.

        If a health tracker is configured, merges in computed health
        scores by matching on ``external_id`` (ticker).
        """
        rows = await self._store.query_market_state(with_events_only=True)
        if not rows:
            return 0

        # Get health scores if tracker is available
        health_scores: Dict[str, float] = {}
        if self._health_tracker is not None:
            try:
                health_scores = self._health_tracker.get_health_scores()
            except Exception:
                self.logger.debug("health_scores_unavailable")

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
                "volume": float(r.get("volume") or 0.0),
                "rankScore": float(r.get("rank_score") or 0.0),
                "healthScore": health_scores.get(r["external_id"]),
                "syncedAt": int(time.time() * 1000),
            }
            for r in rows
        ]

        # Primary: update BroadcastCache
        if self._cache is not None:
            self._cache.update("markets", records, max_age=30)
            self._cache.update(
                "market_stats",
                BroadcastCache.compute_market_stats(records),
                max_age=30,
            )

        # Legacy: push to Convex (transition period, errors are non-fatal)
        if self._convex is not None:
            try:
                for i in range(0, len(records), self.SYNC_BATCH_SIZE):
                    batch = records[i : i + self.SYNC_BATCH_SIZE]
                    await self._convex.mutation(
                        "nexusSync:upsertMarkets", {"markets": batch}
                    )

                # Periodically clean up stale Convex documents (every 10 min)
                now = time.time()
                if now - self._last_cleanup >= 600:
                    await self._cleanup_stale_markets()
                    self._last_cleanup = now
            except Exception:
                self.logger.warning("convex_sync_markets_failed")

        self.logger.info("sync_markets", count=len(records))
        return len(records)

    async def _cleanup_stale_markets(self) -> int:
        """Remove Convex nexusMarkets docs with old syncedAt timestamps.

        Uses a timestamp cutoff (10 minutes ago) so documents not refreshed
        by recent sync cycles get cleaned up. Processes in small batches
        to minimize reactive query amplification.
        """
        if self._convex is None:
            return 0

        cutoff_ts = int((time.time() - 600) * 1000)  # 10 min ago
        total_deleted = 0
        batch_size = 200  # Small batches to limit reactive fan-out

        while True:
            result = await self._convex.mutation(
                "nexusSync:cleanupStaleMarkets",
                {"cutoffTs": cutoff_ts, "batchSize": batch_size},
            )
            deleted = result.get("deleted", 0) if result else 0
            total_deleted += deleted

            if deleted < batch_size:
                break  # No more stale documents

        if total_deleted > 0:
            self.logger.info(
                "cleanup_stale_markets", deleted=total_deleted
            )
        return total_deleted

    async def sync_anomalies(self) -> int:
        """Refresh anomaly data into cache (+ optional Convex). Returns count."""
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

        # Primary: update BroadcastCache
        if self._cache is not None:
            self._cache.update("anomalies", records, max_age=30)
            self._cache.update(
                "anomaly_stats",
                BroadcastCache.compute_anomaly_stats(records),
                max_age=30,
            )

        # Legacy: push to Convex (errors are non-fatal)
        if self._convex is not None:
            try:
                await self._convex.mutation(
                    "nexusSync:upsertAnomalies", {"anomalies": records}
                )
            except Exception:
                self.logger.warning("convex_sync_anomalies_failed")

        self.logger.info("sync_anomalies", count=len(records))
        return len(records)

    async def sync_trending_topics(self) -> int:
        """Refresh topic data into cache (+ optional Convex). Returns count."""
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

        # Primary: update BroadcastCache
        if self._cache is not None:
            self._cache.update("topics", records, max_age=120)

        # Legacy: push to Convex (errors are non-fatal)
        if self._convex is not None:
            try:
                await self._convex.mutation(
                    "nexusSync:upsertTrendingTopics", {"topics": records}
                )
            except Exception:
                self.logger.warning("convex_sync_topics_failed")

        self.logger.info("sync_trending_topics", count=len(records))
        return len(records)

    async def sync_market_summaries(self) -> int:
        """Refresh market summaries into cache (+ optional Convex). Returns count."""
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

        # Primary: update BroadcastCache (summaries not currently served
        # via REST but kept for future use / sync_status)
        if self._cache is not None:
            self._cache.update("summaries", records, max_age=120)

        # Legacy: push to Convex (errors are non-fatal)
        if self._convex is not None:
            try:
                for i in range(0, len(records), self.SYNC_BATCH_SIZE):
                    batch = records[i : i + self.SYNC_BATCH_SIZE]
                    await self._convex.mutation(
                        "nexusSync:upsertMarketSummaries", {"summaries": batch}
                    )
            except Exception:
                self.logger.warning("convex_sync_summaries_failed")

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
                        # v_current_market_state — refresh every 30s for responsiveness
                        if now - last_market_view >= 30:
                            await self._store.refresh_view("v_current_market_state")
                            last_market_view = now
                    await self.sync_markets()
                    await self.sync_anomalies()
                    last_market = now

                # Market summaries (every 5 min)
                if now - last_summary >= self._summary_interval:
                    if hasattr(self._store, "refresh_view"):
                        await self._store.refresh_view("v_market_summaries")
                    await self.sync_market_summaries()
                    last_summary = now

                # Trending topics + hourly activity (every 10 min)
                if now - last_topics >= self._topics_interval:
                    if hasattr(self._store, "refresh_view"):
                        await self._store.refresh_view("v_trending_topics")
                        try:
                            await self._store.refresh_view("v_hourly_activity")
                        except Exception:
                            pass  # View may not exist on older schema deployments
                    await self.sync_trending_topics()
                    last_topics = now

            except Exception:
                self.logger.exception("sync_cycle_error")

            await asyncio.sleep(5)  # Check every 5 seconds

    async def stop(self) -> None:
        """Stop the sync loop."""
        self._running = False
