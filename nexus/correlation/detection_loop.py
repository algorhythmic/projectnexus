"""Periodic anomaly detection loop."""

import asyncio
import time
from collections import Counter
from datetime import datetime, timezone
from typing import List, Optional

from nexus.core.logging import LoggerMixin
from nexus.core.types import WindowConfig
from nexus.correlation.correlator import ClusterCorrelator
from nexus.correlation.cross_platform import CrossPlatformCorrelator
from nexus.correlation.detector import AnomalyDetector, StoredAnomalyContext
from nexus.correlation.series_detector import SeriesPatternDetector
from nexus.correlation.windows import WindowComputer
from nexus.ingestion.health import _get_rss_mb
from nexus.intelligence.narrative import CatalystAnalyzer
from nexus.store.base import BaseStore


class DetectionLoop(LoggerMixin):
    """Runs anomaly detection periodically across all active markets."""

    def __init__(
        self,
        store: BaseStore,
        window_configs: List[WindowConfig],
        interval_seconds: int = 300,
        baseline_hours: int = 24,
        expiry_hours: int = 24,
        cluster_min_markets: int = 0,
        cluster_window_minutes: int = 60,
        cross_platform_enabled: bool = False,
        cross_platform_window_minutes: int = 60,
        retention_days: int = 0,
        max_markets_per_cycle: int = 200,
    ) -> None:
        self._store = store
        self._window_configs = window_configs
        self._interval = interval_seconds
        self._baseline_hours = baseline_hours
        self._expiry_hours = expiry_hours
        self._cluster_min_markets = cluster_min_markets
        self._cluster_window_minutes = cluster_window_minutes
        self._cross_platform_enabled = cross_platform_enabled
        self._cross_platform_window_minutes = cross_platform_window_minutes
        self._retention_days = retention_days
        self._max_markets = max_markets_per_cycle
        self._running = False
        self._task: Optional[asyncio.Task] = None
        # Start from 10 minutes ago (not 0) to avoid scanning all
        # historical markets on first cycle — prevents OOM on restart
        self._last_cycle_ts: int = int(time.time() * 1000) - 600_000
        # Incremental clustering: run every 6 hours if API key is set
        self._last_cluster_ts: float = 0.0
        self._cluster_interval: float = 6 * 3600  # 6 hours
        self._cluster_min_unassigned: int = 10

    async def run_once(self) -> int:
        """Run a single detection cycle. Returns anomaly count."""
        now_ms = int(time.time() * 1000)

        # Expire old anomalies first
        expiry_cutoff = now_ms - (self._expiry_hours * 3600 * 1000)
        expired = await self._store.expire_old_anomalies(expiry_cutoff)
        if expired > 0:
            self.logger.info("expired_anomalies", count=expired)

        # Only scan markets that had events since last cycle
        market_ids = await self._store.get_markets_with_recent_events(
            self._last_cycle_ts
        )
        self._last_cycle_ts = now_ms

        # Cap to prevent OOM on the 1GB Fly.io VM — each market requires
        # multiple DB round-trips for window computation + baseline sampling
        max_markets = self._max_markets
        if len(market_ids) > max_markets:
            self.logger.info(
                "detection_cap",
                total=len(market_ids),
                scanning=max_markets,
            )
            market_ids = market_ids[:max_markets]

        if not market_ids:
            # Log trading hours context for Kalshi (most active 9:30 AM–8 PM ET)
            utc_hour = datetime.now(timezone.utc).hour
            et_hour = (utc_hour - 4) % 24  # Approximate ET (ignores DST)
            outside_peak = et_hour < 9 or et_hour >= 21
            self.logger.info(
                "detection_skip",
                reason="no markets with recent events",
                outside_peak_hours=outside_peak,
            )
            return 0

        rss_before = _get_rss_mb()

        wc = WindowComputer(self._store)
        detector = AnomalyDetector(
            self._store, wc, baseline_hours=self._baseline_hours
        )

        stored_anomalies = await detector.detect_and_store(
            market_ids, self._window_configs, now_ms
        )
        count = len(stored_anomalies)

        # Enrich new anomalies with catalyst analysis
        catalyst_counts: Counter = Counter()
        if stored_anomalies:
            catalyst_counts = await self._enrich_with_catalyst(
                stored_anomalies, now_ms
            )

        # Run cluster correlation if enabled
        cluster_count = 0
        if self._cluster_min_markets > 0:
            correlator = ClusterCorrelator(
                self._store,
                min_cluster_markets=self._cluster_min_markets,
                cluster_window_minutes=self._cluster_window_minutes,
            )
            cluster_count = await correlator.correlate_and_store(now_ms)

        # Run series pattern detection
        series_count = 0
        if len(market_ids) >= 3:
            series_detector = SeriesPatternDetector(
                self._store,
                min_movers=max(3, self._cluster_min_markets),
                window_minutes=self._cluster_window_minutes,
            )
            series_count = await series_detector.detect_and_store(
                market_ids, now_ms
            )

        # Run cross-platform correlation if enabled
        xplat_count = 0
        if self._cross_platform_enabled:
            xplat = CrossPlatformCorrelator(
                self._store,
                window_minutes=self._cross_platform_window_minutes,
            )
            # Refresh links from clusters, then detect
            await xplat.build_links()
            xplat_count = await xplat.correlate_and_store(now_ms)

        # Data retention: prune old events
        pruned = 0
        if self._retention_days > 0:
            cutoff = now_ms - (self._retention_days * 86400 * 1000)
            pruned = await self._store.prune_events(cutoff)
            if pruned > 0:
                self.logger.info("events_pruned", count=pruned)

        # Incremental topic clustering (every 6h if ANTHROPIC_API_KEY set)
        await self._maybe_run_clustering()

        thresholds = {
            "price": self._window_configs[0].price_change_threshold,
            "volume": self._window_configs[0].volume_spike_multiplier,
            "zscore": self._window_configs[0].zscore_threshold,
        } if self._window_configs else {}
        rss_after = _get_rss_mb()
        rss_extra: dict = {}
        if rss_before is not None and rss_after is not None:
            rss_extra["rss_before_mb"] = rss_before
            rss_extra["rss_after_mb"] = rss_after
            rss_extra["rss_delta_mb"] = round(rss_after - rss_before, 1)
        self.logger.info(
            "detection_cycle_complete",
            markets_scanned=len(market_ids),
            anomalies_found=count,
            cluster_anomalies=cluster_count,
            series_anomalies=series_count,
            cross_platform_anomalies=xplat_count,
            catalyst_types=dict(catalyst_counts) if catalyst_counts else {},
            events_pruned=pruned,
            thresholds=thresholds,
            **rss_extra,
        )
        return count + cluster_count + series_count + xplat_count

    async def _enrich_with_catalyst(
        self,
        stored: List[StoredAnomalyContext],
        now_ms: int,
    ) -> Counter:
        """Run CatalystAnalyzer on each new anomaly and store the result.

        Returns a Counter of catalyst_type values for logging.
        """
        analyzer = CatalystAnalyzer()
        counts: Counter = Counter()

        for ctx in stored:
            try:
                # Fetch events in the anomaly's window
                window_start = now_ms - (ctx.window_minutes * 60 * 1000)
                events = await self._store.get_events(
                    market_id=ctx.market_id,
                    since=window_start,
                    limit=500,
                )
                market = await self._store.get_market_by_id(ctx.market_id)

                analysis = analyzer.analyze_events(
                    events, market=market, window_minutes=ctx.window_minutes
                )
                await self._store.update_anomaly_metadata(
                    ctx.anomaly_id, analysis.to_json()
                )
                counts[analysis.catalyst_type] += 1
            except Exception:
                self.logger.debug(
                    "catalyst_enrichment_failed",
                    anomaly_id=ctx.anomaly_id,
                    exc_info=True,
                )

        return counts

    async def _maybe_run_clustering(self) -> None:
        """Run incremental topic clustering if due and API key is available."""
        from nexus.core.config import settings

        if not settings.anthropic_api_key:
            return

        now = time.time()
        if now - self._last_cluster_ts < self._cluster_interval:
            return

        try:
            unassigned = await self._store.count_unassigned_markets()
            if unassigned < self._cluster_min_unassigned:
                return

            self.logger.info(
                "clustering_start",
                unassigned_markets=unassigned,
            )

            from nexus.clustering.clusterer import TopicClusterer
            from nexus.clustering.llm_client import ClaudeClient

            client = ClaudeClient(settings)
            clusterer = TopicClusterer(self._store, client, settings)
            assigned = await clusterer.incremental_cluster()
            cost = client.get_cost_summary()
            await client.close()

            self._last_cluster_ts = now
            self.logger.info(
                "clustering_complete",
                assignments=assigned,
                cost_usd=cost["total_cost_usd"],
                llm_calls=cost["total_requests"],
            )
        except Exception:
            self.logger.exception("clustering_error")

    async def run_forever(self) -> None:
        """Run detection cycles at the configured interval."""
        self._running = True
        while self._running:
            try:
                await self.run_once()
            except Exception:
                self.logger.exception("detection_cycle_error")
            await asyncio.sleep(self._interval)

    async def stop(self) -> None:
        """Stop the detection loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
