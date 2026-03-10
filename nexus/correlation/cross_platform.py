"""Cross-platform correlation detection (Milestone 3.3).

Identifies semantically equivalent markets across platforms and detects
higher-quality anomaly signals when cross-platform pairs move together.
"""

import json
import time
from typing import Dict, List, Optional, Set, Tuple

from nexus.core.logging import LoggerMixin
from nexus.core.types import (
    AnomalyMarketRecord,
    AnomalyRecord,
    AnomalyStatus,
    AnomalyType,
    CrossPlatformLink,
    MarketRecord,
)
from nexus.store.base import BaseStore


class CrossPlatformCorrelator(LoggerMixin):
    """Detects cross-platform anomalies from linked market pairs.

    Two-phase process:
    1. build_links() — Scan topic clusters for markets from different
       platforms that share a cluster.  These are candidate equivalents.
    2. correlate() — For each linked pair, check if both markets have
       recent SINGLE_MARKET anomalies.  If so, emit a CROSS_PLATFORM
       anomaly with enriched direction/divergence metadata.
    """

    def __init__(
        self,
        store: BaseStore,
        window_minutes: int = 60,
    ) -> None:
        self._store = store
        self._window_minutes = window_minutes

    # ------------------------------------------------------------------
    # Phase 1: Build cross-platform links from shared clusters
    # ------------------------------------------------------------------

    async def build_links(self) -> int:
        """Scan clusters and create cross-platform links.

        For each topic cluster, finds markets from different platforms
        and links them.  Returns number of new/updated links.
        """
        clusters = await self._store.get_clusters()
        if not clusters:
            return 0

        # Get all active markets keyed by id for platform lookups
        all_markets = await self._store.get_active_markets()
        market_map: Dict[int, MarketRecord] = {
            m.id: m for m in all_markets if m.id is not None
        }

        now_ms = int(time.time() * 1000)
        link_count = 0

        for cluster in clusters:
            if cluster.id is None:
                continue

            members = await self._store.get_cluster_markets(cluster.id)
            # Group by platform
            by_platform: Dict[str, List[Tuple[int, float]]] = {}
            for mid, conf in members:
                market = market_map.get(mid)
                if market is None:
                    continue
                platform = market.platform.value
                by_platform.setdefault(platform, []).append((mid, conf))

            # Need markets from at least 2 platforms to create links
            platforms = list(by_platform.keys())
            if len(platforms) < 2:
                continue

            # Create pairwise links across platforms
            for i, p1 in enumerate(platforms):
                for p2 in platforms[i + 1:]:
                    for mid_a, conf_a in by_platform[p1]:
                        for mid_b, conf_b in by_platform[p2]:
                            link_conf = min(conf_a, conf_b)
                            link = CrossPlatformLink(
                                market_id_a=mid_a,
                                market_id_b=mid_b,
                                confidence=link_conf,
                                method="cluster",
                                created_at=now_ms,
                            )
                            await self._store.upsert_cross_platform_link(link)
                            link_count += 1

        self.logger.info(
            "cross_platform_links_built",
            link_count=link_count,
            clusters_scanned=len(clusters),
        )
        return link_count

    # ------------------------------------------------------------------
    # Phase 2: Detect cross-platform anomalies
    # ------------------------------------------------------------------

    async def correlate(self, now_ms: int) -> List[AnomalyRecord]:
        """Check linked pairs for concurrent anomalies.

        Returns CROSS_PLATFORM anomaly records (not yet stored).
        """
        links = await self._store.get_cross_platform_links()
        if not links:
            return []

        window_start = now_ms - (self._window_minutes * 60 * 1000)

        # Get all recent single-market anomalies
        recent = await self._store.get_anomalies(
            since=window_start,
            anomaly_type=AnomalyType.SINGLE_MARKET.value,
            status=AnomalyStatus.ACTIVE,
            limit=10000,
        )
        if not recent:
            return []

        # Build market_id -> anomalies map
        anomaly_map: Dict[int, List[AnomalyRecord]] = {}
        for a in recent:
            if a.id is None:
                continue
            market_links = await self._store.get_anomaly_markets(a.id)
            for ml in market_links:
                anomaly_map.setdefault(ml.market_id, []).append(a)

        # Check for existing CROSS_PLATFORM anomalies (dedup)
        existing = await self._store.get_anomalies(
            since=window_start,
            anomaly_type=AnomalyType.CROSS_PLATFORM.value,
            limit=10000,
        )
        already_emitted: Set[Tuple[int, int]] = set()
        for e in existing:
            if e.metadata:
                try:
                    meta = json.loads(e.metadata)
                    pair = (meta.get("market_id_a", 0), meta.get("market_id_b", 0))
                    already_emitted.add(tuple(sorted(pair)))
                except (json.JSONDecodeError, TypeError):
                    pass

        results: List[AnomalyRecord] = []

        for link in links:
            pair_key = tuple(sorted([link.market_id_a, link.market_id_b]))
            if pair_key in already_emitted:
                continue

            anomalies_a = anomaly_map.get(link.market_id_a, [])
            anomalies_b = anomaly_map.get(link.market_id_b, [])

            if not anomalies_a or not anomalies_b:
                continue

            anomaly = self._build_cross_platform_anomaly(
                link, anomalies_a, anomalies_b, window_start, now_ms
            )
            results.append(anomaly)
            already_emitted.add(pair_key)

            self.logger.info(
                "cross_platform_anomaly_detected",
                market_id_a=link.market_id_a,
                market_id_b=link.market_id_b,
                severity=anomaly.severity,
            )

        return results

    async def correlate_and_store(self, now_ms: int) -> int:
        """Detect and store cross-platform anomalies. Returns count."""
        anomalies = await self.correlate(now_ms)
        for anomaly in anomalies:
            market_links = self._extract_market_links(anomaly)
            await self._store.insert_anomaly(anomaly, market_links)
        return len(anomalies)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_cross_platform_anomaly(
        self,
        link: CrossPlatformLink,
        anomalies_a: List[AnomalyRecord],
        anomalies_b: List[AnomalyRecord],
        window_start: int,
        now_ms: int,
    ) -> AnomalyRecord:
        """Build a CROSS_PLATFORM anomaly from a linked pair."""
        sev_a = max(a.severity for a in anomalies_a)
        sev_b = max(a.severity for a in anomalies_b)
        # Cross-platform pairs get a severity boost (higher confidence signal)
        raw_severity = (sev_a + sev_b) / 2.0
        boosted = min(raw_severity * 1.2, 1.0)

        dir_a = self._infer_direction(anomalies_a)
        dir_b = self._infer_direction(anomalies_b)

        if dir_a == dir_b and dir_a != "undetermined":
            signal = "convergent"
            direction = dir_a
        elif dir_a != "undetermined" and dir_b != "undetermined" and dir_a != dir_b:
            signal = "divergent"
            direction = "mixed"
        else:
            signal = "undetermined"
            direction = "undetermined"

        summary = (
            f"Cross-platform {signal}: markets {link.market_id_a} & "
            f"{link.market_id_b} ({direction}, severity {boosted:.2f})"
        )

        metadata_dict = {
            "market_id_a": link.market_id_a,
            "market_id_b": link.market_id_b,
            "link_confidence": link.confidence,
            "signal_type": signal,
            "direction": direction,
            "severity_a": round(sev_a, 4),
            "severity_b": round(sev_b, 4),
        }

        return AnomalyRecord(
            anomaly_type=AnomalyType.CROSS_PLATFORM,
            severity=round(boosted, 4),
            topic_cluster_id=None,
            market_count=2,
            window_start=window_start,
            detected_at=now_ms,
            summary=summary,
            metadata=json.dumps(metadata_dict),
        )

    @staticmethod
    def _infer_direction(anomalies: List[AnomalyRecord]) -> str:
        """Infer price direction from anomaly summaries."""
        positive = 0
        negative = 0
        for a in anomalies:
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

    @staticmethod
    def _extract_market_links(
        anomaly: AnomalyRecord,
    ) -> List[AnomalyMarketRecord]:
        """Build market links from anomaly metadata."""
        if not anomaly.metadata:
            return []
        try:
            meta = json.loads(anomaly.metadata)
        except (json.JSONDecodeError, TypeError):
            return []

        links = []
        for key in ("market_id_a", "market_id_b"):
            mid = meta.get(key)
            if mid is not None:
                links.append(AnomalyMarketRecord(
                    anomaly_id=0,
                    market_id=mid,
                    price_delta=None,
                    volume_ratio=None,
                ))
        return links
