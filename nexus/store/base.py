"""Abstract base class for the Nexus event store."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

from nexus.core.types import DiscoveredMarket, EventRecord, MarketRecord


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

    @abstractmethod
    async def close(self) -> None:
        """Close the database connection."""
        ...
