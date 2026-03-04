"""Tests for store data integrity query methods."""

import pytest

from nexus.core.types import DiscoveredMarket, EventRecord, EventType, Platform


async def _insert_market(store, external_id: str = "INTEG-1") -> int:
    """Insert a test market and return its id."""
    market = DiscoveredMarket(
        platform=Platform.KALSHI,
        external_id=external_id,
        title=f"Integrity Test {external_id}",
        yes_price=0.5,
    )
    await store.upsert_markets([market])
    stored = await store.get_market_by_external_id("kalshi", external_id)
    return stored.id


async def _insert_event(
    store, market_id: int, event_type: EventType, new_value: float, timestamp: int
) -> None:
    """Insert a single test event."""
    await store.insert_events([
        EventRecord(
            market_id=market_id,
            event_type=event_type,
            new_value=new_value,
            timestamp=timestamp,
        )
    ])


class TestEventCountInRange:
    async def test_counts_within_range(self, tmp_store):
        """Only counts events within the specified range."""
        mid = await _insert_market(tmp_store)
        await _insert_event(tmp_store, mid, EventType.PRICE_CHANGE, 0.5, 1000)
        await _insert_event(tmp_store, mid, EventType.PRICE_CHANGE, 0.6, 2000)
        await _insert_event(tmp_store, mid, EventType.PRICE_CHANGE, 0.7, 3000)

        count = await tmp_store.get_event_count_in_range(since=1500, until=2500)
        assert count == 1  # only the event at t=2000

    async def test_since_only(self, tmp_store):
        """With only since, counts from that point forward."""
        mid = await _insert_market(tmp_store)
        await _insert_event(tmp_store, mid, EventType.PRICE_CHANGE, 0.5, 1000)
        await _insert_event(tmp_store, mid, EventType.PRICE_CHANGE, 0.6, 2000)

        count = await tmp_store.get_event_count_in_range(since=1500)
        assert count == 1

    async def test_empty_range(self, tmp_store):
        """Range with no events returns zero."""
        count = await tmp_store.get_event_count_in_range(since=9000, until=9999)
        assert count == 0


class TestDuplicateEventCount:
    async def test_no_duplicates(self, tmp_store):
        """Distinct events return zero duplicates."""
        mid = await _insert_market(tmp_store)
        await _insert_event(tmp_store, mid, EventType.PRICE_CHANGE, 0.5, 1000)
        await _insert_event(tmp_store, mid, EventType.PRICE_CHANGE, 0.6, 2000)

        count = await tmp_store.get_duplicate_event_count()
        assert count == 0

    async def test_detects_duplicates(self, tmp_store):
        """Events with identical key fields are counted as duplicates."""
        mid = await _insert_market(tmp_store)
        # Insert same event twice
        await _insert_event(tmp_store, mid, EventType.PRICE_CHANGE, 0.5, 1000)
        await _insert_event(tmp_store, mid, EventType.PRICE_CHANGE, 0.5, 1000)

        count = await tmp_store.get_duplicate_event_count()
        assert count == 1  # one extra copy


class TestEventGaps:
    async def test_no_gaps(self, tmp_store):
        """Events close together don't trigger gap detection."""
        mid = await _insert_market(tmp_store)
        for i in range(5):
            await _insert_event(
                tmp_store, mid, EventType.PRICE_CHANGE, 0.5, 1000 + i * 1000
            )

        gaps = await tmp_store.get_event_gaps(gap_threshold_ms=300_000)
        assert len(gaps) == 0

    async def test_detects_gap(self, tmp_store):
        """A 10-minute gap is detected with 5-minute threshold."""
        mid = await _insert_market(tmp_store)
        await _insert_event(tmp_store, mid, EventType.PRICE_CHANGE, 0.5, 1000)
        await _insert_event(
            tmp_store, mid, EventType.PRICE_CHANGE, 0.6, 1000 + 600_000
        )  # 10 minutes later

        gaps = await tmp_store.get_event_gaps(gap_threshold_ms=300_000)
        assert len(gaps) == 1
        start, end, duration = gaps[0]
        assert duration == 600_000

    async def test_gap_threshold(self, tmp_store):
        """Gap is not detected when below threshold."""
        mid = await _insert_market(tmp_store)
        await _insert_event(tmp_store, mid, EventType.PRICE_CHANGE, 0.5, 1000)
        await _insert_event(
            tmp_store, mid, EventType.PRICE_CHANGE, 0.6, 1000 + 200_000
        )  # 200s later

        gaps = await tmp_store.get_event_gaps(gap_threshold_ms=300_000)
        assert len(gaps) == 0


class TestOrderingViolations:
    async def test_ordered_events(self, tmp_store):
        """Properly ordered events have zero violations."""
        mid = await _insert_market(tmp_store)
        await _insert_event(tmp_store, mid, EventType.PRICE_CHANGE, 0.5, 1000)
        await _insert_event(tmp_store, mid, EventType.PRICE_CHANGE, 0.6, 2000)
        await _insert_event(tmp_store, mid, EventType.PRICE_CHANGE, 0.7, 3000)

        violations = await tmp_store.get_ordering_violations()
        assert violations == 0

    async def test_detects_out_of_order(self, tmp_store):
        """Events inserted with decreasing timestamps are detected."""
        mid = await _insert_market(tmp_store)
        await _insert_event(tmp_store, mid, EventType.PRICE_CHANGE, 0.5, 3000)
        await _insert_event(tmp_store, mid, EventType.PRICE_CHANGE, 0.6, 1000)

        violations = await tmp_store.get_ordering_violations()
        assert violations == 1


class TestEventTypeDistribution:
    async def test_counts_by_type(self, tmp_store):
        """Events are correctly counted by type."""
        mid = await _insert_market(tmp_store)
        await _insert_event(tmp_store, mid, EventType.PRICE_CHANGE, 0.5, 1000)
        await _insert_event(tmp_store, mid, EventType.PRICE_CHANGE, 0.6, 2000)
        await _insert_event(tmp_store, mid, EventType.TRADE, 0.5, 3000)
        await _insert_event(tmp_store, mid, EventType.NEW_MARKET, 0.5, 4000)

        dist = await tmp_store.get_event_type_distribution()
        assert dist["price_change"] == 2
        assert dist["trade"] == 1
        assert dist["new_market"] == 1

    async def test_empty_store(self, tmp_store):
        """Empty store returns empty distribution."""
        dist = await tmp_store.get_event_type_distribution()
        assert dist == {}
