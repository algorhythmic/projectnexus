"""Prompt templates and response parsing for LLM-based market clustering."""

import json
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from nexus.core.types import MarketRecord, TopicCluster


# ------------------------------------------------------------------
# Response dataclasses
# ------------------------------------------------------------------


@dataclass
class MarketAssignment:
    """A single market-to-cluster assignment from LLM output."""

    market_id: int
    confidence: float


@dataclass
class ClusterResult:
    """A cluster with its assigned markets from batch clustering."""

    name: str
    description: Optional[str]
    markets: List[MarketAssignment]


@dataclass
class BatchClusteringResult:
    """Full result of a batch clustering LLM call."""

    clusters: List[ClusterResult] = field(default_factory=list)


@dataclass
class IncrementalAssignment:
    """A single market assignment from incremental clustering."""

    market_id: int
    cluster_name: str
    cluster_description: Optional[str]
    is_new_cluster: bool
    confidence: float


@dataclass
class IncrementalClusteringResult:
    """Full result of an incremental clustering LLM call."""

    assignments: List[IncrementalAssignment] = field(default_factory=list)


# ------------------------------------------------------------------
# Prompt builders
# ------------------------------------------------------------------

_BATCH_SYSTEM = """\
You are a prediction market analyst. Your task is to group prediction markets \
into topic clusters based on their semantic content. Each cluster should \
represent a coherent real-world topic area (e.g., "US Federal Reserve Policy", \
"2026 NFL Season", "US Immigration Policy").

Rules:
1. Each market must be assigned to exactly one cluster.
2. Create between 5 and 30 clusters depending on the diversity of markets.
3. Cluster names should be specific but not overly narrow. \
Good: "US Federal Reserve Policy". Bad: "Fed rate cut March 2026".
4. Assign a confidence score (0.0-1.0) for each assignment. \
Use 0.9+ for obvious matches, 0.5-0.7 for ambiguous ones.
5. If a market doesn't fit any cluster well, create a "Miscellaneous" cluster \
with low confidence.

Respond with valid JSON only, no other text."""

_INCREMENTAL_SYSTEM = """\
You are a prediction market analyst. You will be given a list of NEW markets \
and a list of EXISTING topic clusters. Your task is to assign each new market \
to the most appropriate existing cluster, or create a new cluster if none fit.

Rules:
1. Prefer assigning to existing clusters when the fit is reasonable \
(confidence >= 0.5).
2. Only create a new cluster if no existing cluster fits at all.
3. Assign a confidence score (0.0-1.0) for each assignment.
4. Each market must be assigned to exactly one cluster.

Respond with valid JSON only, no other text."""


def build_batch_clustering_prompt(
    markets: List[MarketRecord],
) -> Tuple[str, str]:
    """Build system + user prompts for batch clustering."""
    lines = ["Group the following prediction markets into topic clusters.", ""]
    lines.append("Markets:")
    for m in markets:
        desc = f" -- {m.description}" if m.description else ""
        lines.append(f'  [id={m.id}] "{m.title}"{desc}')

    lines.append("")
    lines.append("Respond with this JSON structure:")
    lines.append("""{
  "clusters": [
    {
      "name": "Cluster Name",
      "description": "Brief description of the topic",
      "markets": [
        {"market_id": 42, "confidence": 0.95}
      ]
    }
  ]
}""")

    return _BATCH_SYSTEM, "\n".join(lines)


def build_incremental_prompt(
    markets: List[MarketRecord],
    existing_clusters: List[TopicCluster],
) -> Tuple[str, str]:
    """Build system + user prompts for incremental clustering."""
    lines = [
        "Assign the following NEW markets to existing clusters or create new ones.",
        "",
        "EXISTING CLUSTERS:",
    ]
    for c in existing_clusters:
        desc = f": {c.description}" if c.description else ""
        lines.append(f'- "{c.name}"{desc}')

    lines.append("")
    lines.append("NEW MARKETS:")
    for m in markets:
        desc = f" -- {m.description}" if m.description else ""
        lines.append(f'  [id={m.id}] "{m.title}"{desc}')

    lines.append("")
    lines.append("Respond with this JSON structure:")
    lines.append("""{
  "assignments": [
    {
      "market_id": 42,
      "cluster_name": "Existing Cluster Name",
      "cluster_description": null,
      "is_new_cluster": false,
      "confidence": 0.92
    }
  ]
}""")

    return _INCREMENTAL_SYSTEM, "\n".join(lines)


# ------------------------------------------------------------------
# Response parsers
# ------------------------------------------------------------------


def _extract_json(content: str) -> Optional[dict]:
    """Extract JSON object from LLM response, handling code blocks."""
    # Strip markdown code blocks
    text = content.strip()
    if text.startswith("```"):
        # Remove opening fence (possibly ```json)
        first_newline = text.index("\n") if "\n" in text else len(text)
        text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    # Find JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def parse_batch_response(content: str) -> BatchClusteringResult:
    """Parse a batch clustering LLM response into structured result."""
    data = _extract_json(content)
    if not data or "clusters" not in data:
        return BatchClusteringResult()

    clusters = []
    for c in data["clusters"]:
        markets = [
            MarketAssignment(
                market_id=m.get("market_id", 0),
                confidence=m.get("confidence", 0.5),
            )
            for m in c.get("markets", [])
        ]
        clusters.append(
            ClusterResult(
                name=c.get("name", "Unknown"),
                description=c.get("description"),
                markets=markets,
            )
        )

    return BatchClusteringResult(clusters=clusters)


def parse_incremental_response(content: str) -> IncrementalClusteringResult:
    """Parse an incremental clustering LLM response."""
    data = _extract_json(content)
    if not data or "assignments" not in data:
        return IncrementalClusteringResult()

    assignments = [
        IncrementalAssignment(
            market_id=a.get("market_id", 0),
            cluster_name=a.get("cluster_name", "Unknown"),
            cluster_description=a.get("cluster_description"),
            is_new_cluster=a.get("is_new_cluster", False),
            confidence=a.get("confidence", 0.5),
        )
        for a in data["assignments"]
    ]

    return IncrementalClusteringResult(assignments=assignments)
