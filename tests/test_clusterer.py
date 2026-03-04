"""Tests for TopicClusterer with mocked LLM."""

import json
import time

import pytest

from nexus.clustering.clusterer import TopicClusterer
from nexus.clustering.llm_client import ClaudeResponse
from nexus.core.config import Settings
from nexus.core.types import DiscoveredMarket, Platform, TopicCluster


class MockClaudeClient:
    """Mock LLM client that returns pre-built responses."""

    def __init__(self, responses: list[str] = None):
        self._responses = responses or []
        self._call_index = 0
        self._calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> ClaudeResponse:
        self._calls.append((system, user))
        content = self._responses[self._call_index] if self._call_index < len(self._responses) else "{}"
        self._call_index += 1
        return ClaudeResponse(
            content=content, input_tokens=100, output_tokens=50, cost_usd=0.001
        )

    def get_cost_summary(self) -> dict:
        return {"total_cost_usd": 0.0, "total_requests": len(self._calls),
                "total_input_tokens": 0, "total_output_tokens": 0}

    async def close(self) -> None:
        pass


async def _insert_markets(store, count: int = 3) -> list[int]:
    """Insert test markets and return their IDs."""
    ids = []
    for i in range(count):
        market = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id=f"CLUST-{i}",
            title=f"Test Market {i}",
            yes_price=0.5,
        )
        await store.upsert_markets([market])
        stored = await store.get_market_by_external_id("kalshi", f"CLUST-{i}")
        ids.append(stored.id)
    return ids


def _settings() -> Settings:
    return Settings(
        anthropic_api_key="test-key",
        clustering_batch_size=30,
        clustering_min_confidence=0.6,
    )


class TestTopicClusterer:
    async def test_batch_cluster_no_markets(self, tmp_store):
        """No unassigned markets returns 0."""
        mock = MockClaudeClient()
        clusterer = TopicClusterer(tmp_store, mock, _settings())
        count = await clusterer.batch_cluster()
        assert count == 0
        assert len(mock._calls) == 0

    async def test_batch_cluster_creates_clusters(self, tmp_store):
        """Batch clustering creates clusters in store."""
        ids = await _insert_markets(tmp_store, 3)

        response = json.dumps({
            "clusters": [
                {
                    "name": "Finance",
                    "description": "Financial markets",
                    "markets": [
                        {"market_id": ids[0], "confidence": 0.9},
                        {"market_id": ids[1], "confidence": 0.85},
                    ]
                },
                {
                    "name": "Tech",
                    "description": "Technology markets",
                    "markets": [
                        {"market_id": ids[2], "confidence": 0.8},
                    ]
                },
            ]
        })

        mock = MockClaudeClient([response])
        clusterer = TopicClusterer(tmp_store, mock, _settings())
        count = await clusterer.batch_cluster()

        assert count == 3
        clusters = await tmp_store.get_clusters()
        assert len(clusters) == 2
        names = {c.name for c in clusters}
        assert names == {"Finance", "Tech"}

    async def test_batch_cluster_filters_low_confidence(self, tmp_store):
        """Assignments below min_confidence are skipped."""
        ids = await _insert_markets(tmp_store, 2)

        response = json.dumps({
            "clusters": [{
                "name": "Mixed",
                "description": None,
                "markets": [
                    {"market_id": ids[0], "confidence": 0.9},  # above 0.6
                    {"market_id": ids[1], "confidence": 0.3},  # below 0.6
                ]
            }]
        })

        mock = MockClaudeClient([response])
        clusterer = TopicClusterer(tmp_store, mock, _settings())
        count = await clusterer.batch_cluster()

        assert count == 1  # Only the high-confidence one

    async def test_incremental_uses_existing(self, tmp_store):
        """Incremental clustering assigns to existing clusters."""
        ids = await _insert_markets(tmp_store, 2)
        now = int(time.time() * 1000)

        # Pre-create a cluster and assign first market
        cid = await tmp_store.insert_cluster(TopicCluster(
            name="Finance", description="Money stuff",
            created_at=now, updated_at=now,
        ))
        await tmp_store.assign_market_to_cluster(ids[0], cid, 0.9)

        # LLM assigns second market to existing cluster
        response = json.dumps({
            "assignments": [{
                "market_id": ids[1],
                "cluster_name": "Finance",
                "cluster_description": None,
                "is_new_cluster": False,
                "confidence": 0.85,
            }]
        })

        mock = MockClaudeClient([response])
        clusterer = TopicClusterer(tmp_store, mock, _settings())
        count = await clusterer.incremental_cluster()

        assert count == 1
        markets = await tmp_store.get_cluster_markets(cid)
        assert len(markets) == 2

    async def test_incremental_creates_new_cluster(self, tmp_store):
        """Incremental can create a new cluster."""
        ids = await _insert_markets(tmp_store, 2)
        now = int(time.time() * 1000)

        # Pre-create existing cluster
        cid = await tmp_store.insert_cluster(TopicCluster(
            name="Finance", description=None,
            created_at=now, updated_at=now,
        ))
        await tmp_store.assign_market_to_cluster(ids[0], cid, 0.9)

        response = json.dumps({
            "assignments": [{
                "market_id": ids[1],
                "cluster_name": "Space",
                "cluster_description": "Space exploration",
                "is_new_cluster": True,
                "confidence": 0.88,
            }]
        })

        mock = MockClaudeClient([response])
        clusterer = TopicClusterer(tmp_store, mock, _settings())
        count = await clusterer.incremental_cluster()

        assert count == 1
        clusters = await tmp_store.get_clusters()
        names = {c.name for c in clusters}
        assert "Space" in names

    async def test_incremental_falls_back_to_batch(self, tmp_store):
        """No existing clusters triggers batch mode fallback."""
        ids = await _insert_markets(tmp_store, 2)

        response = json.dumps({
            "clusters": [{
                "name": "General",
                "description": None,
                "markets": [
                    {"market_id": ids[0], "confidence": 0.9},
                    {"market_id": ids[1], "confidence": 0.8},
                ]
            }]
        })

        mock = MockClaudeClient([response])
        clusterer = TopicClusterer(tmp_store, mock, _settings())
        count = await clusterer.incremental_cluster()

        assert count == 2

    async def test_batch_respects_batch_size(self, tmp_store):
        """Multiple batches produce multiple LLM calls."""
        ids = await _insert_markets(tmp_store, 5)
        s = _settings()
        s_small = Settings(
            anthropic_api_key="test",
            clustering_batch_size=2,
            clustering_min_confidence=0.6,
        )

        # First call: batch clustering (2 markets)
        # Remaining calls: incremental (2 markets each)
        responses = [
            json.dumps({"clusters": [{
                "name": "A", "description": None,
                "markets": [{"market_id": ids[0], "confidence": 0.9},
                             {"market_id": ids[1], "confidence": 0.9}]
            }]}),
            json.dumps({"assignments": [
                {"market_id": ids[2], "cluster_name": "A", "cluster_description": None,
                 "is_new_cluster": False, "confidence": 0.9},
                {"market_id": ids[3], "cluster_name": "A", "cluster_description": None,
                 "is_new_cluster": False, "confidence": 0.9},
            ]}),
            json.dumps({"assignments": [
                {"market_id": ids[4], "cluster_name": "A", "cluster_description": None,
                 "is_new_cluster": False, "confidence": 0.9},
            ]}),
        ]

        mock = MockClaudeClient(responses)
        clusterer = TopicClusterer(tmp_store, mock, s_small)
        count = await clusterer.batch_cluster()

        assert count == 5
        assert len(mock._calls) == 3  # 3 batches of size 2, 2, 1
