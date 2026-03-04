"""Tests for clustering prompt construction and response parsing."""

import json

import pytest

from nexus.clustering.prompts import (
    BatchClusteringResult,
    IncrementalClusteringResult,
    build_batch_clustering_prompt,
    build_incremental_prompt,
    parse_batch_response,
    parse_incremental_response,
)
from nexus.core.types import MarketRecord, Platform, TopicCluster


def _make_market(id: int, title: str) -> MarketRecord:
    return MarketRecord(
        id=id,
        platform=Platform.KALSHI,
        external_id=f"MKT-{id}",
        title=title,
        first_seen_at=1000000,
        last_updated_at=1000000,
    )


def _make_cluster(name: str, desc: str = None) -> TopicCluster:
    return TopicCluster(
        id=1, name=name, description=desc,
        created_at=1000000, updated_at=1000000,
    )


class TestBatchPrompt:
    def test_format_structure(self):
        """System and user prompts have expected structure."""
        markets = [_make_market(1, "Will the Fed cut rates?")]
        system, user = build_batch_clustering_prompt(markets)

        assert "topic clusters" in system.lower()
        assert "confidence" in system.lower()
        assert "JSON" in system
        assert "Markets:" in user
        assert '"clusters"' in user

    def test_includes_market_ids(self):
        """All market IDs appear in the user prompt."""
        markets = [
            _make_market(42, "Fed rate cut"),
            _make_market(99, "Bitcoin price"),
        ]
        _, user = build_batch_clustering_prompt(markets)

        assert "[id=42]" in user
        assert "[id=99]" in user
        assert "Fed rate cut" in user
        assert "Bitcoin price" in user


class TestIncrementalPrompt:
    def test_includes_clusters(self):
        """Existing cluster names appear in the prompt."""
        markets = [_make_market(1, "New market")]
        clusters = [
            _make_cluster("Fed Policy", "Interest rates"),
            _make_cluster("Crypto"),
        ]
        _, user = build_incremental_prompt(markets, clusters)

        assert "Fed Policy" in user
        assert "Crypto" in user
        assert "EXISTING CLUSTERS:" in user
        assert "NEW MARKETS:" in user


class TestParseBatchResponse:
    def test_valid_json(self):
        """Valid JSON parses into correct structure."""
        response = json.dumps({
            "clusters": [
                {
                    "name": "Fed Policy",
                    "description": "Interest rate decisions",
                    "markets": [
                        {"market_id": 1, "confidence": 0.95},
                        {"market_id": 2, "confidence": 0.8},
                    ]
                },
                {
                    "name": "Crypto",
                    "description": "Cryptocurrency markets",
                    "markets": [
                        {"market_id": 3, "confidence": 0.9},
                    ]
                },
            ]
        })

        result = parse_batch_response(response)
        assert len(result.clusters) == 2
        assert result.clusters[0].name == "Fed Policy"
        assert len(result.clusters[0].markets) == 2
        assert result.clusters[0].markets[0].market_id == 1
        assert result.clusters[0].markets[0].confidence == 0.95

    def test_json_in_codeblock(self):
        """JSON wrapped in markdown code blocks parses correctly."""
        response = '```json\n{"clusters": [{"name": "Test", "description": null, "markets": [{"market_id": 1, "confidence": 0.9}]}]}\n```'

        result = parse_batch_response(response)
        assert len(result.clusters) == 1
        assert result.clusters[0].name == "Test"

    def test_invalid_response(self):
        """Malformed response returns empty result."""
        result = parse_batch_response("This is not JSON at all.")
        assert isinstance(result, BatchClusteringResult)
        assert len(result.clusters) == 0


class TestParseIncrementalResponse:
    def test_valid_json(self):
        """Valid incremental JSON parses correctly."""
        response = json.dumps({
            "assignments": [
                {
                    "market_id": 42,
                    "cluster_name": "Fed Policy",
                    "cluster_description": None,
                    "is_new_cluster": False,
                    "confidence": 0.92,
                },
                {
                    "market_id": 43,
                    "cluster_name": "Space Exploration",
                    "cluster_description": "SpaceX and NASA",
                    "is_new_cluster": True,
                    "confidence": 0.85,
                },
            ]
        })

        result = parse_incremental_response(response)
        assert len(result.assignments) == 2
        assert result.assignments[0].market_id == 42
        assert result.assignments[0].is_new_cluster is False
        assert result.assignments[1].is_new_cluster is True

    def test_invalid_response(self):
        """Malformed response returns empty result."""
        result = parse_incremental_response("not json")
        assert isinstance(result, IncrementalClusteringResult)
        assert len(result.assignments) == 0
