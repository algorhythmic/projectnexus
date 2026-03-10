"""Shared Pydantic models and enums for Nexus."""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class Platform(str, Enum):
    """Supported prediction market platforms."""

    KALSHI = "kalshi"
    POLYMARKET = "polymarket"


class EventType(str, Enum):
    """Types of normalized market events."""

    PRICE_CHANGE = "price_change"
    VOLUME_UPDATE = "volume_update"
    STATUS_CHANGE = "status_change"
    NEW_MARKET = "new_market"
    TRADE = "trade"


class MarketRecord(BaseModel):
    """A market as stored in the database."""

    id: Optional[int] = None
    platform: Platform
    external_id: str
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    is_active: bool = True
    first_seen_at: int  # Unix ms
    last_updated_at: int  # Unix ms


class EventRecord(BaseModel):
    """A normalized event as stored in the database."""

    id: Optional[int] = None
    market_id: int
    event_type: EventType
    old_value: Optional[float] = None
    new_value: float
    metadata: Optional[str] = None  # JSON string
    timestamp: int  # Unix ms


class DiscoveredMarket(BaseModel):
    """A market discovered from a platform API, before storage.

    This is the output of an adapter's discover() method --
    a normalized representation of market metadata.
    """

    platform: Platform
    external_id: str
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    is_active: bool = True
    yes_price: Optional[float] = None
    no_price: Optional[float] = None
    volume: Optional[float] = None
    end_date: Optional[str] = None  # ISO 8601
    raw_data: Optional[Dict[str, Any]] = None


# ------------------------------------------------------------------
# Phase 2: Anomaly Detection Types
# ------------------------------------------------------------------


class AnomalyType(str, Enum):
    """Classification of detected anomalies."""

    SINGLE_MARKET = "single_market"
    CLUSTER = "cluster"
    CROSS_PLATFORM = "cross_platform"


class AnomalyStatus(str, Enum):
    """Lifecycle status of an anomaly."""

    ACTIVE = "active"
    EXPIRED = "expired"
    ACKNOWLEDGED = "acknowledged"


class WindowConfig(BaseModel):
    """Configuration for a single detection window."""

    window_minutes: int
    price_change_threshold: float
    volume_spike_multiplier: float
    zscore_threshold: float


class WindowStats(BaseModel):
    """Computed statistics for a market within a time window."""

    market_id: int
    window_minutes: int
    window_start: int  # Unix ms
    window_end: int  # Unix ms
    price_start: Optional[float] = None
    price_end: Optional[float] = None
    price_delta: Optional[float] = None
    price_change_pct: Optional[float] = None
    volume_total: float = 0.0
    trade_count: int = 0
    event_count: int = 0


class HistoricalBaseline(BaseModel):
    """Historical baseline statistics for Z-score computation."""

    market_id: int
    metric: str  # "price_change_pct" or "volume"
    mean: float
    stddev: float
    sample_count: int


class AnomalyRecord(BaseModel):
    """A detected anomaly as stored in the database."""

    id: Optional[int] = None
    anomaly_type: AnomalyType
    severity: float
    topic_cluster_id: Optional[int] = None
    market_count: int
    window_start: int  # Unix ms
    detected_at: int  # Unix ms
    summary: Optional[str] = None
    status: AnomalyStatus = AnomalyStatus.ACTIVE
    metadata: Optional[str] = None  # JSON string


class AnomalyMarketRecord(BaseModel):
    """Junction record linking an anomaly to an affected market."""

    anomaly_id: int
    market_id: int
    price_delta: Optional[float] = None
    volume_ratio: Optional[float] = None


class TopicCluster(BaseModel):
    """A semantic grouping of related markets (Milestone 2.2)."""

    id: Optional[int] = None
    name: str
    description: Optional[str] = None
    created_at: int  # Unix ms
    updated_at: int  # Unix ms


class ClusterAssignment(BaseModel):
    """A market-to-cluster assignment with metadata."""

    market_id: int
    cluster_id: int
    cluster_name: str
    confidence: float  # 0.0-1.0
    assigned_at: int  # Unix ms


class CrossPlatformLink(BaseModel):
    """A semantic equivalence link between markets on different platforms."""

    id: Optional[int] = None
    market_id_a: int  # Market on platform A
    market_id_b: int  # Market on platform B
    confidence: float  # 0.0-1.0
    method: str  # "cluster" (same cluster, different platforms) or "llm"
    created_at: int  # Unix ms
