"""PostgreSQL data refresh layer for the REST API.

Reads from PostgreSQL materialized views and populates an in-memory
BroadcastCache that the Starlette REST API serves to clients.
"""

import asyncio
import time
from typing import Any, Dict

from nexus.api.cache import BroadcastCache
from nexus.core.logging import LoggerMixin


class SyncLayer(LoggerMixin):
    """Orchestrates PostgreSQL → BroadcastCache refresh.

    Refresh targets:
        markets          ← v_current_market_state    (every 60s)
        activeAnomalies  ← v_active_anomalies        (every 60s)
        trendingTopics   ← v_trending_topics          (every 10min)
        marketSummaries  ← v_market_summaries         (every 5min)

    If a ``health_tracker`` is provided, the market refresh merges in
    computed health scores from the in-memory intelligence engine.
    """

    def __init__(
        self,
        store: Any,  # PostgresStore with view query methods
        cache: BroadcastCache,
        market_interval: int = 60,
        summary_interval: int = 300,
        topics_interval: int = 600,
        health_tracker: Any = None,  # MarketHealthTracker
    ) -> None:
        self._store = store
        self._cache = cache
        self._market_interval = market_interval
        self._summary_interval = summary_interval
        self._topics_interval = topics_interval
        self._health_tracker = health_tracker
        self._running = False

    # ------------------------------------------------------------------
    # One-shot refresh methods
    # ------------------------------------------------------------------

    async def sync_markets(self) -> int:
        """Refresh market data into cache. Returns record count."""
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

        self._cache.update("markets", records, max_age=30)
        self._cache.update(
            "market_stats",
            BroadcastCache.compute_market_stats(records),
            max_age=30,
        )

        self.logger.info("sync_markets", count=len(records))
        return len(records)

    async def sync_anomalies(self) -> int:
        """Refresh anomaly data into cache. Returns record count."""
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

        self._cache.update("anomalies", records, max_age=30)
        self._cache.update(
            "anomaly_stats",
            BroadcastCache.compute_anomaly_stats(records),
            max_age=30,
        )

        self.logger.info("sync_anomalies", count=len(records))
        return len(records)

    async def sync_trending_topics(self) -> int:
        """Refresh topic data into cache. Returns record count."""
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

        self._cache.update("topics", records, max_age=120)

        self.logger.info("sync_trending_topics", count=len(records))
        return len(records)

    async def sync_market_summaries(self) -> int:
        """Refresh market summaries into cache. Returns record count."""
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

        self._cache.update("summaries", records, max_age=120)

        self.logger.info("sync_market_summaries", count=len(records))
        return len(records)

    async def sync_all(self) -> Dict[str, int]:
        """Run all refresh operations once. Returns counts per target."""
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
    # Continuous refresh loop
    # ------------------------------------------------------------------

    async def run_forever(self) -> None:
        """Run scheduled refresh loops at configured intervals."""
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
                        await self._store.refresh_view("v_active_anomalies")
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
        """Stop the refresh loop."""
        self._running = False
