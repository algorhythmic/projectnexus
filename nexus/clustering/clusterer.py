"""Topic clustering orchestrator using LLM-based classification."""

import time
from typing import List

from nexus.clustering.llm_client import ClaudeClient
from nexus.clustering.prompts import (
    BatchClusteringResult,
    IncrementalClusteringResult,
    build_batch_clustering_prompt,
    build_incremental_prompt,
    parse_batch_response,
    parse_incremental_response,
)
from nexus.core.config import Settings
from nexus.core.logging import LoggerMixin
from nexus.core.types import MarketRecord, TopicCluster
from nexus.store.base import BaseStore


class TopicClusterer(LoggerMixin):
    """Orchestrates LLM-based topic clustering of prediction markets.

    Two modes:
    - batch_cluster(): Process all unassigned markets from scratch.
    - incremental_cluster(): Classify new markets against existing clusters.
    """

    def __init__(
        self,
        store: BaseStore,
        llm_client: ClaudeClient,
        settings: Settings,
    ) -> None:
        self._store = store
        self._llm = llm_client
        self._settings = settings

    async def batch_cluster(self) -> int:
        """Cluster all unassigned markets. Returns total assignments made."""
        markets = await self._store.get_unassigned_markets()
        if not markets:
            self.logger.info("batch_cluster_skip", reason="no unassigned markets")
            return 0

        batch_size = self._settings.clustering_batch_size
        batches = [
            markets[i : i + batch_size]
            for i in range(0, len(markets), batch_size)
        ]

        self.logger.info(
            "batch_cluster_start",
            total_markets=len(markets),
            num_batches=len(batches),
        )

        total_assigned = 0

        # First batch: full batch clustering
        result = await self._process_batch(batches[0])
        total_assigned += await self._apply_batch_result(result)

        # Remaining batches: incremental against clusters from first batch
        for batch in batches[1:]:
            existing = await self._store.get_clusters()
            inc_result = await self._process_incremental_batch(batch, existing)
            total_assigned += await self._apply_incremental_result(inc_result)

        self.logger.info("batch_cluster_complete", total_assigned=total_assigned)
        return total_assigned

    async def incremental_cluster(self) -> int:
        """Classify unassigned markets against existing clusters."""
        markets = await self._store.get_unassigned_markets()
        if not markets:
            self.logger.info("incremental_skip", reason="no unassigned markets")
            return 0

        existing = await self._store.get_clusters()
        if not existing:
            self.logger.info("incremental_fallback", reason="no existing clusters")
            return await self.batch_cluster()

        batch_size = self._settings.clustering_batch_size
        batches = [
            markets[i : i + batch_size]
            for i in range(0, len(markets), batch_size)
        ]

        total_assigned = 0
        for batch in batches:
            result = await self._process_incremental_batch(batch, existing)
            total_assigned += await self._apply_incremental_result(result)
            # Refresh clusters in case new ones were created
            existing = await self._store.get_clusters()

        self.logger.info(
            "incremental_complete", total_assigned=total_assigned
        )
        return total_assigned

    async def _process_batch(
        self, markets: List[MarketRecord]
    ) -> BatchClusteringResult:
        """Send a batch of markets to the LLM for clustering."""
        system, user = build_batch_clustering_prompt(markets)
        response = await self._llm.complete(system, user)
        return parse_batch_response(response.content)

    async def _process_incremental_batch(
        self,
        markets: List[MarketRecord],
        existing_clusters: List[TopicCluster],
    ) -> IncrementalClusteringResult:
        """Classify a batch of new markets against existing clusters."""
        system, user = build_incremental_prompt(markets, existing_clusters)
        response = await self._llm.complete(system, user)
        return parse_incremental_response(response.content)

    async def _apply_batch_result(self, result: BatchClusteringResult) -> int:
        """Persist batch clustering results. Returns assignments made."""
        now_ms = int(time.time() * 1000)
        assigned = 0

        for cr in result.clusters:
            # Find or create cluster
            cluster = await self._store.get_cluster_by_name(cr.name)
            if cluster is None:
                cid = await self._store.insert_cluster(
                    TopicCluster(
                        name=cr.name,
                        description=cr.description,
                        created_at=now_ms,
                        updated_at=now_ms,
                    )
                )
            else:
                cid = cluster.id

            for ma in cr.markets:
                if ma.confidence >= self._settings.clustering_min_confidence:
                    await self._store.assign_market_to_cluster(
                        ma.market_id, cid, ma.confidence
                    )
                    assigned += 1

        return assigned

    async def _apply_incremental_result(
        self, result: IncrementalClusteringResult
    ) -> int:
        """Persist incremental results. Returns assignments made."""
        now_ms = int(time.time() * 1000)
        assigned = 0

        for ia in result.assignments:
            if ia.confidence < self._settings.clustering_min_confidence:
                continue

            if ia.is_new_cluster:
                cluster = await self._store.get_cluster_by_name(ia.cluster_name)
                if cluster is None:
                    cid = await self._store.insert_cluster(
                        TopicCluster(
                            name=ia.cluster_name,
                            description=ia.cluster_description,
                            created_at=now_ms,
                            updated_at=now_ms,
                        )
                    )
                else:
                    cid = cluster.id
            else:
                cluster = await self._store.get_cluster_by_name(ia.cluster_name)
                if cluster is None:
                    # LLM referenced a cluster that doesn't exist; create it
                    cid = await self._store.insert_cluster(
                        TopicCluster(
                            name=ia.cluster_name,
                            description=ia.cluster_description,
                            created_at=now_ms,
                            updated_at=now_ms,
                        )
                    )
                else:
                    cid = cluster.id

            await self._store.assign_market_to_cluster(
                ia.market_id, cid, ia.confidence
            )
            assigned += 1

        return assigned
