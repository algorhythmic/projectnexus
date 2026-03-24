"""In-memory broadcast data cache for the REST API.

Pre-serializes JSON responses so each HTTP request is a dict lookup +
byte copy — no per-request serialization or database query.
"""

import hashlib
import json
import time
from typing import Any, Dict, List, NamedTuple, Optional


class CacheEntry(NamedTuple):
    json_bytes: bytes
    etag: str
    last_modified: float
    max_age: int
    data: Any  # raw Python objects for server-side filtering


class BroadcastCache:
    """Thread-safe in-memory cache for broadcast data."""

    def __init__(self) -> None:
        self._entries: Dict[str, CacheEntry] = {}

    def update(self, key: str, data: Any, max_age: int = 60) -> None:
        """Serialize data and store as a cache entry."""
        json_bytes = json.dumps(data, separators=(",", ":")).encode()
        etag = hashlib.md5(json_bytes).hexdigest()
        self._entries[key] = CacheEntry(
            json_bytes=json_bytes,
            etag=etag,
            last_modified=time.time(),
            max_age=max_age,
            data=data,
        )

    def get(self, key: str) -> Optional[CacheEntry]:
        """Get a cache entry by key, or None if not cached."""
        return self._entries.get(key)

    def get_status(self) -> Dict[str, Any]:
        """Return cache metadata for the /status endpoint."""
        status: Dict[str, Any] = {}
        for key, entry in self._entries.items():
            count = len(entry.data) if isinstance(entry.data, list) else 1
            status[key] = {
                "lastRefresh": int(entry.last_modified * 1000),
                "recordCount": count,
            }
        return status

    @staticmethod
    def compute_market_stats(markets: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Pre-compute market statistics from the cached market list."""
        total = len(markets)
        active = sum(1 for m in markets if m.get("isActive"))
        platform_counts: Dict[str, int] = {}
        category_counts: Dict[str, int] = {}
        for m in markets:
            p = m.get("platform", "unknown")
            platform_counts[p] = platform_counts.get(p, 0) + 1
            c = m.get("category", "")
            if c:
                category_counts[c] = category_counts.get(c, 0) + 1
        return {
            "totalMarkets": total,
            "activeMarkets": active,
            "platformCounts": platform_counts,
            "categoryCounts": category_counts,
        }

    @staticmethod
    def compute_anomaly_stats(anomalies: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Pre-compute anomaly statistics from the cached anomaly list."""
        count = len(anomalies)
        if count == 0:
            return {
                "activeCount": 0,
                "avgSeverity": 0,
                "bySeverityBucket": {"high": 0, "medium": 0, "low": 0},
            }
        total_severity = sum(a.get("severity", 0) for a in anomalies)
        high = sum(1 for a in anomalies if a.get("severity", 0) >= 0.7)
        medium = sum(
            1 for a in anomalies if 0.4 <= a.get("severity", 0) < 0.7
        )
        low = count - high - medium
        return {
            "activeCount": count,
            "avgSeverity": total_severity / count,
            "bySeverityBucket": {"high": high, "medium": medium, "low": low},
        }
