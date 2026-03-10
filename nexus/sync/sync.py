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

    # ------------------------------------------------------------------
    # One-shot sync methods
    # ------------------------------------------------------------------

    async def sync_markets(self) -> int:
        """Push current market state to Convex. Returns record count."""
        rows = await self._store.query_market_state()
        if not rows:
            return 0

        records = [
            {
                "marketId": r["market_id"],
                "platform": r["platform"],
                "externalId": r["external_id"],
                "title": r["title"],
                "category": r.get("category") or "",
                "isActive": bool(r["is_active"]),
                "lastPrice": r.get("last_price"),
                "lastPriceTs": r.get("last_price_ts"),
                "lastVolume": r.get("last_volume"),
                "lastVolumeTs": r.get("last_volume_ts"),
                "syncedAt": int(time.time() * 1000),
            }
            for r in rows
        ]

        await self._convex.mutation(
            "nexusSync:upsertMarkets", {"markets": records}
        )
        self.logger.info("sync_markets", count=len(records))
        return len(records)

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

        await self._convex.mutation(
            "nexusSync:upsertMarketSummaries", {"summaries": records}
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

        while self._running:
            now = time.time()

            try:
                # Markets + anomalies (highest frequency)
                if now - last_market >= self._market_interval:
                    if hasattr(self._store, "refresh_views"):
                        await self._store.refresh_views()
                    await self.sync_markets()
                    await self.sync_anomalies()
                    last_market = now

                # Market summaries
                if now - last_summary >= self._summary_interval:
                    await self.sync_market_summaries()
                    last_summary = now

                # Trending topics
                if now - last_topics >= self._topics_interval:
                    await self.sync_trending_topics()
                    last_topics = now

            except Exception:
                self.logger.exception("sync_cycle_error")

            await asyncio.sleep(5)  # Check every 5 seconds

    async def stop(self) -> None:
        """Stop the sync loop."""
        self._running = False
