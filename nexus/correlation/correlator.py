"""Cluster-level correlation detection for concurrent anomalies."""

import json
import statistics
from typing import Dict, List

from nexus.core.logging import LoggerMixin
from nexus.core.types import (
    AnomalyMarketRecord,
    AnomalyRecord,
    AnomalyStatus,
    AnomalyType,
    TopicCluster,
)
from nexus.store.base import BaseStore


class ClusterCorrelator(LoggerMixin):
    """Detects cluster-level anomalies by correlating single-market anomalies.

    After single-market detection, scans each topic cluster to check how
    many markets triggered individual anomalies within a time window.
    If >= min_cluster_markets fired, emits a CLUSTER anomaly.
    """

    def __init__(
        self,
        store: BaseStore,
        min_cluster_markets: int = 2,
        cluster_window_minutes: int = 60,
    ) -> None:
        self._store = store
        self._min_markets = min_cluster_markets
        self._window_minutes = cluster_window_minutes

    async def correlate(self, now_ms: int) -> List[AnomalyRecord]:
        """Scan all topic clusters for concurrent anomalies.

        Returns a list of CLUSTER anomaly records (not yet stored).
        """
        clusters = await self._store.get_clusters()
        if not clusters:
            return []

        window_start = now_ms - (self._window_minutes * 60 * 1000)

        # Fetch all recent SINGLE_MARKET anomalies in the window
        recent_anomalies = await self._store.get_anomalies(
            since=window_start,
            anomaly_type=AnomalyType.SINGLE_MARKET.value,
            status=AnomalyStatus.ACTIVE,
            limit=10000,
        )

        if not recent_anomalies:
            return []

        # Build market_id -> list of anomalies mapping
        anomaly_market_map: Dict[int, List[AnomalyRecord]] = {}
        for anomaly in recent_anomalies:
            if anomaly.id is None:
                continue
            market_links = await self._store.get_anomaly_markets(anomaly.id)
            for link in market_links:
                anomaly_market_map.setdefault(link.market_id, []).append(anomaly)

        # Check for existing CLUSTER anomalies in window (for dedup)
        existing_cluster_anomalies = await self._store.get_anomalies(
            since=window_start,
            anomaly_type=AnomalyType.CLUSTER.value,
            limit=10000,
        )
        already_emitted_cluster_ids = {
            a.topic_cluster_id for a in existing_cluster_anomalies
        }

        cluster_anomalies: List[AnomalyRecord] = []

        for cluster in clusters:
            if cluster.id is None:
                continue

            if cluster.id in already_emitted_cluster_ids:
                continue

            cluster_markets = await self._store.get_cluster_markets(cluster.id)
            cluster_market_ids = {mid for mid, _conf in cluster_markets}

            # Find which cluster markets have anomalies
            affected: Dict[int, List[AnomalyRecord]] = {}
            for mid in cluster_market_ids:
                if mid in anomaly_market_map:
                    affected[mid] = anomaly_market_map[mid]

            if len(affected) < self._min_markets:
                continue

            anomaly = self._build_cluster_anomaly(
                cluster, affected, window_start, now_ms
            )
            cluster_anomalies.append(anomaly)

            self.logger.info(
                "cluster_anomaly_detected",
                cluster_name=cluster.name,
                cluster_id=cluster.id,
                affected_markets=len(affected),
            )

        return cluster_anomalies

    async def correlate_and_store(self, now_ms: int) -> int:
        """Detect cluster anomalies and store them. Returns count stored."""
        anomalies = await self.correlate(now_ms)

        for anomaly in anomalies:
            links = await self._build_market_links(anomaly)
            await self._store.insert_anomaly(anomaly, links)

        return len(anomalies)

    def _build_cluster_anomaly(
        self,
        cluster: TopicCluster,
        affected: Dict[int, List[AnomalyRecord]],
        window_start: int,
        now_ms: int,
    ) -> AnomalyRecord:
        """Construct a CLUSTER AnomalyRecord from affected markets."""
        # Aggregate severity: mean of max severities per market
        market_severities = [
            max(a.severity for a in market_anomalies)
            for market_anomalies in affected.values()
        ]
        agg_severity = round(statistics.mean(market_severities), 4)

        direction = self._detect_direction(affected)

        summary = (
            f"[{cluster.name}] {len(affected)} markets {direction}: "
            f"cluster anomaly (severity {agg_severity:.2f})"
        )

        metadata_dict = {
            "cluster_name": cluster.name,
            "direction": direction,
            "affected_market_ids": sorted(affected.keys()),
        }

        return AnomalyRecord(
            anomaly_type=AnomalyType.CLUSTER,
            severity=agg_severity,
            topic_cluster_id=cluster.id,
            market_count=len(affected),
            window_start=window_start,
            detected_at=now_ms,
            summary=summary,
            metadata=json.dumps(metadata_dict),
        )

    @staticmethod
    def _detect_direction(
        affected: Dict[int, List[AnomalyRecord]],
    ) -> str:
        """Determine aggregate direction from anomaly summaries."""
        positive = 0
        negative = 0
        for market_anomalies in affected.values():
            for a in market_anomalies:
                if a.summary and "price" in a.summary.lower():
                    if "+" in a.summary:
                        positive += 1
                    elif "-" in a.summary:
                        negative += 1

        if positive > 0 and negative == 0:
            return "bullish"
        if negative > 0 and positive == 0:
            return "bearish"
        if positive > 0 and negative > 0:
            return "mixed"
        return "undetermined"

    async def _build_market_links(
        self, anomaly: AnomalyRecord
    ) -> List[AnomalyMarketRecord]:
        """Build AnomalyMarketRecord links for a cluster anomaly."""
        if anomaly.metadata is None:
            return []

        try:
            meta = json.loads(anomaly.metadata)
        except (json.JSONDecodeError, TypeError):
            return []

        market_ids = meta.get("affected_market_ids", [])
        links: List[AnomalyMarketRecord] = []

        for mid in market_ids:
            # Get most recent single-market anomaly for this market
            market_anomalies = await self._store.get_anomalies(
                market_id=mid,
                anomaly_type=AnomalyType.SINGLE_MARKET.value,
                limit=1,
            )
            price_delta = None
            volume_ratio = None
            if market_anomalies and market_anomalies[0].id is not None:
                existing_links = await self._store.get_anomaly_markets(
                    market_anomalies[0].id
                )
                if existing_links:
                    price_delta = existing_links[0].price_delta
                    volume_ratio = existing_links[0].volume_ratio

            links.append(AnomalyMarketRecord(
                anomaly_id=0,
                market_id=mid,
                price_delta=price_delta,
                volume_ratio=volume_ratio,
            ))

        return links
