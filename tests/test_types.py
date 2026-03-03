"""Tests for Pydantic models and enums."""

import pytest
from pydantic import ValidationError

from nexus.core.types import (
    DiscoveredMarket,
    EventRecord,
    EventType,
    MarketRecord,
    Platform,
)


class TestPlatformEnum:
    def test_values(self):
        assert Platform.KALSHI.value == "kalshi"
        assert Platform.POLYMARKET.value == "polymarket"

    def test_from_string(self):
        assert Platform("kalshi") == Platform.KALSHI


class TestEventTypeEnum:
    def test_all_values(self):
        assert EventType.PRICE_CHANGE.value == "price_change"
        assert EventType.VOLUME_UPDATE.value == "volume_update"
        assert EventType.STATUS_CHANGE.value == "status_change"
        assert EventType.NEW_MARKET.value == "new_market"


class TestDiscoveredMarket:
    def test_minimal_creation(self):
        m = DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id="ABC",
            title="Test",
        )
        assert m.platform == Platform.KALSHI
        assert m.is_active is True
        assert m.yes_price is None

    def test_full_creation(self):
        m = DiscoveredMarket(
            platform=Platform.POLYMARKET,
            external_id="XYZ",
            title="Full Market",
            description="A test market",
            category="Politics",
            is_active=False,
            yes_price=0.65,
            no_price=0.35,
            volume=1234.5,
            end_date="2026-12-31T00:00:00Z",
            raw_data={"key": "value"},
        )
        assert m.volume == 1234.5
        assert m.raw_data == {"key": "value"}

    def test_missing_required_fields_raises(self):
        with pytest.raises(ValidationError):
            DiscoveredMarket(platform=Platform.KALSHI)  # type: ignore[call-arg]


class TestMarketRecord:
    def test_creation_with_id(self):
        r = MarketRecord(
            id=42,
            platform=Platform.KALSHI,
            external_id="REC-1",
            title="Record",
            first_seen_at=1000,
            last_updated_at=2000,
        )
        assert r.id == 42

    def test_optional_id(self):
        r = MarketRecord(
            platform=Platform.KALSHI,
            external_id="REC-2",
            title="No ID",
            first_seen_at=1000,
            last_updated_at=2000,
        )
        assert r.id is None


class TestEventRecord:
    def test_creation(self):
        e = EventRecord(
            market_id=1,
            event_type=EventType.PRICE_CHANGE,
            old_value=0.5,
            new_value=0.6,
            timestamp=1000,
        )
        assert e.old_value == 0.5

    def test_optional_old_value(self):
        e = EventRecord(
            market_id=1,
            event_type=EventType.NEW_MARKET,
            new_value=0.5,
            timestamp=1000,
        )
        assert e.old_value is None
