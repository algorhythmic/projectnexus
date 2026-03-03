"""Abstract base class for the Nexus event store."""

from abc import ABC, abstractmethod
from typing import List, Optional

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

    @abstractmethod
    async def close(self) -> None:
        """Close the database connection."""
        ...
