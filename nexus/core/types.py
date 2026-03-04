"""Shared Pydantic models and enums for Nexus."""

from enum import Enum
from typing import Any, Dict, Optional

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
