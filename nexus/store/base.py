"""Abstract base class for the Nexus event store."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

from nexus.core.types import (
    AnomalyMarketRecord,
    AnomalyRecord,
    AnomalyStatus,
    CrossPlatformLink,
    DiscoveredMarket,
    EventRecord,
    MarketRecord,
    TopicCluster,
)


class BaseStore(ABC):
    """Abstract interface for the event store.

    Implementations: SQLiteStore (Phase 1), PostgresStore (Phase 2).
    """

    @abstractmethod
    async def initialize(self) -> None:
        """Create tables and indexes if they don't exist."""
        ...

    @abstractmethod
    async def upsert_markets(self, markets: List[DiscoveredMarket]) -> int:
        """Insert or update markets. Returns count of newly inserted markets."""
        ...

    @abstractmethod
    async def get_market_by_external_id(
        self, platform: str, external_id: str
    ) -> Optional[MarketRecord]:
        """Look up a single market by platform + external_id."""
        ...

    @abstractmethod
    async def get_active_markets(
        self, platform: Optional[str] = None
    ) -> List[MarketRecord]:
        """List all active markets, optionally filtered by platform."""
        ...

    @abstractmethod
    async def deactivate_stale_markets(
        self, platform: str, before_ms: int
    ) -> int:
        """Set is_active=FALSE for markets of the given platform whose
        last_updated_at is older than before_ms. Returns count of
        deactivated markets."""
        ...

    @abstractmethod
    async def insert_events(self, events: List[EventRecord]) -> int:
        """Batch-insert events. Returns the number of rows inserted."""
        ...

    @abstractmethod
    async def get_events(
        self,
        market_id: Optional[int] = None,
        event_type: Optional[str] = None,
        since: Optional[int] = None,
        limit: int = 1000,
    ) -> List[EventRecord]:
        """Query events with optional filters."""
        ...

    @abstractmethod
    async def get_market_count(self) -> int:
        """Return total number of markets."""
        ...

    @abstractmethod
    async def get_event_count(self) -> int:
        """Return total number of events."""
        ...

    @abstractmethod
    async def get_event_time_range(self) -> Tuple[Optional[int], Optional[int]]:
        """Return (min_timestamp, max_timestamp) across all events, or (None, None)."""
        ...

    # ------------------------------------------------------------------
    # Data integrity queries (Milestone 1.3)
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_event_count_in_range(
        self, since: int, until: Optional[int] = None
    ) -> int:
        """Count events in a timestamp range (Unix ms)."""
        ...

    @abstractmethod
    async def get_duplicate_event_count(
        self, since: Optional[int] = None, until: Optional[int] = None
    ) -> int:
        """Count duplicate events (same market_id, event_type, timestamp, new_value)."""
        ...

    @abstractmethod
    async def get_event_gaps(
        self,
        gap_threshold_ms: int = 300_000,
        since: Optional[int] = None,
        until: Optional[int] = None,
    ) -> List[Tuple[int, int, int]]:
        """Find time gaps exceeding threshold. Returns (start_ms, end_ms, duration_ms) tuples."""
        ...

    @abstractmethod
    async def get_ordering_violations(
        self, since: Optional[int] = None, until: Optional[int] = None
    ) -> int:
        """Count events where a higher id has a lower timestamp."""
        ...

    @abstractmethod
    async def get_event_type_distribution(
        self, since: Optional[int] = None, until: Optional[int] = None
    ) -> Dict[str, int]:
        """Count events grouped by event_type."""
        ...

    # ------------------------------------------------------------------
    # Anomaly detection queries (Milestone 2.1)
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_events_in_window(
        self,
        market_id: int,
        event_type: str,
        window_start: int,
        window_end: int,
    ) -> List[EventRecord]:
        """Get events for a market in a time window, ordered by timestamp ASC."""
        ...

    @abstractmethod
    async def insert_anomaly(
        self,
        anomaly: AnomalyRecord,
        market_links: List[AnomalyMarketRecord],
    ) -> int:
        """Insert an anomaly and its market junction rows. Returns anomaly id."""
        ...

    @abstractmethod
    async def get_anomalies(
        self,
        since: Optional[int] = None,
        until: Optional[int] = None,
        status: Optional[AnomalyStatus] = None,
        anomaly_type: Optional[str] = None,
        min_severity: Optional[float] = None,
        market_id: Optional[int] = None,
        limit: int = 100,
    ) -> List[AnomalyRecord]:
        """Query anomalies with optional filters."""
        ...

    @abstractmethod
    async def get_anomaly_markets(
        self, anomaly_id: int
    ) -> List[AnomalyMarketRecord]:
        """Get market junction rows for an anomaly."""
        ...

    @abstractmethod
    async def update_anomaly_status(
        self, anomaly_id: int, status: AnomalyStatus
    ) -> None:
        """Update the lifecycle status of an anomaly."""
        ...

    @abstractmethod
    async def expire_old_anomalies(self, older_than: int) -> int:
        """Bulk-expire active anomalies detected before older_than (Unix ms).
        Returns count of expired anomalies."""
        ...

    # ------------------------------------------------------------------
    # Topic clustering (Milestone 2.2)
    # ------------------------------------------------------------------

    @abstractmethod
    async def insert_cluster(self, cluster: TopicCluster) -> int:
        """Insert a topic cluster. Returns the cluster id."""
        ...

    @abstractmethod
    async def get_clusters(self) -> List[TopicCluster]:
        """Get all topic clusters."""
        ...

    @abstractmethod
    async def get_cluster_by_name(self, name: str) -> Optional[TopicCluster]:
        """Look up a cluster by exact name."""
        ...

    @abstractmethod
    async def assign_market_to_cluster(
        self, market_id: int, cluster_id: int, confidence: float
    ) -> None:
        """Create or update a market-to-cluster assignment."""
        ...

    @abstractmethod
    async def get_cluster_markets(
        self, cluster_id: int
    ) -> List[Tuple[int, float]]:
        """Get (market_id, confidence) pairs for a cluster."""
        ...

    @abstractmethod
    async def get_market_clusters(
        self, market_id: int
    ) -> List[Tuple[int, str, float]]:
        """Get (cluster_id, cluster_name, confidence) for a market."""
        ...

    @abstractmethod
    async def get_unassigned_markets(self) -> List[MarketRecord]:
        """Get active markets not in any cluster."""
        ...

    # ------------------------------------------------------------------
    # Cross-platform links (Milestone 3.3)
    # ------------------------------------------------------------------

    @abstractmethod
    async def upsert_cross_platform_link(self, link: CrossPlatformLink) -> int:
        """Insert or update a cross-platform link. Returns the link id."""
        ...

    @abstractmethod
    async def get_cross_platform_links(
        self, market_id: Optional[int] = None
    ) -> List[CrossPlatformLink]:
        """Get cross-platform links, optionally filtered by market_id."""
        ...

    @abstractmethod
    async def get_cross_platform_pair(
        self, market_id_a: int, market_id_b: int
    ) -> Optional[CrossPlatformLink]:
        """Look up a specific cross-platform link between two markets."""
        ...

    # ------------------------------------------------------------------
    # Data retention (Milestone 3.3)
    # ------------------------------------------------------------------

    @abstractmethod
    async def prune_events(self, older_than: int) -> int:
        """Delete events with timestamp < older_than (Unix ms).
        Returns count of deleted events."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the database connection."""
        ...
