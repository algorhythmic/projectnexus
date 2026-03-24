"""PostgreSQL event store implementation using asyncpg."""

import json
import time
from typing import Dict, List, Optional, Tuple

import asyncpg

from nexus.core.logging import LoggerMixin
from nexus.core.types import (
    AnomalyMarketRecord,
    AnomalyRecord,
    AnomalyStatus,
    AnomalyType,
    CrossPlatformLink,
    DiscoveredMarket,
    EventRecord,
    EventType,
    MarketRecord,
    Platform,
    TopicCluster,
)
from nexus.store.base import BaseStore

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS markets (
    id BIGSERIAL PRIMARY KEY,
    platform TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    category TEXT,
    end_date TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    first_seen_at BIGINT NOT NULL,
    last_updated_at BIGINT NOT NULL,
    UNIQUE(platform, external_id)
);

CREATE INDEX IF NOT EXISTS idx_markets_platform ON markets(platform);
CREATE INDEX IF NOT EXISTS idx_markets_category ON markets(category);
CREATE INDEX IF NOT EXISTS idx_markets_is_active ON markets(is_active);

CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    market_id BIGINT NOT NULL REFERENCES markets(id),
    event_type TEXT NOT NULL,
    old_value DOUBLE PRECISION,
    new_value DOUBLE PRECISION NOT NULL,
    metadata TEXT,
    timestamp BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_market_id ON events(market_id);
CREATE INDEX IF NOT EXISTS idx_events_event_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_events_market_type_ts
    ON events(market_id, event_type, timestamp);

CREATE TABLE IF NOT EXISTS topic_clusters (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    created_at BIGINT NOT NULL,
    updated_at BIGINT NOT NULL
);

CREATE TABLE IF NOT EXISTS market_cluster_memberships (
    market_id BIGINT NOT NULL REFERENCES markets(id),
    cluster_id BIGINT NOT NULL REFERENCES topic_clusters(id),
    confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    assigned_at BIGINT NOT NULL,
    PRIMARY KEY (market_id, cluster_id)
);

CREATE TABLE IF NOT EXISTS anomalies (
    id BIGSERIAL PRIMARY KEY,
    anomaly_type TEXT NOT NULL,
    severity DOUBLE PRECISION NOT NULL,
    topic_cluster_id BIGINT REFERENCES topic_clusters(id),
    market_count INTEGER NOT NULL,
    window_start BIGINT NOT NULL,
    detected_at BIGINT NOT NULL,
    summary TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    metadata TEXT
);

CREATE INDEX IF NOT EXISTS idx_anomalies_detected_at ON anomalies(detected_at);
CREATE INDEX IF NOT EXISTS idx_anomalies_status ON anomalies(status);
CREATE INDEX IF NOT EXISTS idx_anomalies_severity ON anomalies(severity);

CREATE TABLE IF NOT EXISTS anomaly_markets (
    anomaly_id BIGINT NOT NULL REFERENCES anomalies(id),
    market_id BIGINT NOT NULL REFERENCES markets(id),
    price_delta DOUBLE PRECISION,
    volume_ratio DOUBLE PRECISION,
    PRIMARY KEY (anomaly_id, market_id)
);

CREATE INDEX IF NOT EXISTS idx_anomaly_markets_market_id ON anomaly_markets(market_id);

CREATE TABLE IF NOT EXISTS cross_platform_links (
    id BIGSERIAL PRIMARY KEY,
    market_id_a BIGINT NOT NULL REFERENCES markets(id),
    market_id_b BIGINT NOT NULL REFERENCES markets(id),
    confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    method TEXT NOT NULL DEFAULT 'cluster',
    created_at BIGINT NOT NULL,
    UNIQUE(market_id_a, market_id_b)
);

CREATE INDEX IF NOT EXISTS idx_cross_platform_links_a ON cross_platform_links(market_id_a);
CREATE INDEX IF NOT EXISTS idx_cross_platform_links_b ON cross_platform_links(market_id_b);
"""

# Materialized views for common read patterns
_MATERIALIZED_VIEWS = frozenset({
    "v_current_market_state",
    "v_active_anomalies",
    "v_trending_topics",
    "v_market_summaries",
    "v_hourly_activity",
})

_VIEWS_SQL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS v_current_market_state AS
SELECT
    m.id AS market_id,
    m.platform,
    m.external_id,
    m.title,
    m.description,
    m.category,
    m.end_date,
    m.is_active,
    latest_price.new_value AS last_price,
    latest_price.timestamp AS last_price_ts,
    latest_volume.new_value AS last_volume,
    latest_volume.timestamp AS last_volume_ts,
    COALESCE(m.volume, 0) AS volume,
    -- Rank score: volume (40%) + activity recency (30%) + expiry proximity (30%)
    (
        COALESCE(
            CASE WHEN m.volume > 0
                 THEN LEAST(LN(m.volume + 1) / 10.0, 1.0)
                 ELSE 0.0
            END, 0.0
        ) * 0.4
        +
        COALESCE(
            CASE WHEN latest_price.timestamp IS NOT NULL
                 THEN LEAST(
                     1.0 / GREATEST(
                         EXTRACT(EPOCH FROM (NOW() - TO_TIMESTAMP(latest_price.timestamp / 1000.0))) / 3600.0,
                         0.1
                     ),
                     1.0
                 )
                 ELSE 0.0
            END, 0.0
        ) * 0.3
        +
        COALESCE(
            CASE WHEN m.end_date IS NOT NULL AND m.end_date != ''
                      AND m.end_date::timestamptz > NOW()
                 THEN LEAST(1.0 / GREATEST(EXTRACT(EPOCH FROM (m.end_date::timestamptz - NOW())) / 86400.0, 0.01), 1.0)
                 ELSE 0.0
            END, 0.0
        ) * 0.3
    ) AS rank_score
FROM markets m
LEFT JOIN LATERAL (
    SELECT new_value, timestamp FROM events
    WHERE market_id = m.id AND event_type = 'price_change'
    ORDER BY timestamp DESC LIMIT 1
) latest_price ON TRUE
LEFT JOIN LATERAL (
    SELECT new_value, timestamp FROM events
    WHERE market_id = m.id AND event_type = 'volume_update'
    ORDER BY timestamp DESC LIMIT 1
) latest_volume ON TRUE
WHERE m.is_active = TRUE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_v_current_market_state_id
    ON v_current_market_state(market_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS v_active_anomalies AS
SELECT
    a.id AS anomaly_id,
    a.anomaly_type,
    a.severity,
    a.market_count,
    a.detected_at,
    a.summary,
    a.metadata,
    tc.name AS cluster_name
FROM anomalies a
LEFT JOIN topic_clusters tc ON tc.id = a.topic_cluster_id
WHERE a.status = 'active'
ORDER BY a.detected_at DESC;

CREATE UNIQUE INDEX IF NOT EXISTS idx_v_active_anomalies_id
    ON v_active_anomalies(anomaly_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS v_trending_topics AS
SELECT
    tc.id AS cluster_id,
    tc.name,
    tc.description,
    COUNT(DISTINCT mcm.market_id) AS market_count,
    COUNT(DISTINCT a.id) AS anomaly_count,
    MAX(a.severity) AS max_severity
FROM topic_clusters tc
LEFT JOIN market_cluster_memberships mcm ON mcm.cluster_id = tc.id
LEFT JOIN anomaly_markets am ON am.market_id = mcm.market_id
LEFT JOIN anomalies a ON a.id = am.anomaly_id AND a.status = 'active'
GROUP BY tc.id, tc.name, tc.description
ORDER BY anomaly_count DESC, market_count DESC;

CREATE UNIQUE INDEX IF NOT EXISTS idx_v_trending_topics_id
    ON v_trending_topics(cluster_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS v_market_summaries AS
SELECT
    m.id AS market_id,
    m.platform,
    m.title,
    m.category,
    COUNT(e.id) AS event_count,
    MIN(e.timestamp) AS first_event_ts,
    MAX(e.timestamp) AS last_event_ts
FROM markets m
LEFT JOIN events e ON e.market_id = m.id
GROUP BY m.id, m.platform, m.title, m.category;

CREATE UNIQUE INDEX IF NOT EXISTS idx_v_market_summaries_id
    ON v_market_summaries(market_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS v_hourly_activity AS
SELECT
    (timestamp / 3600000) * 3600000 AS hour_bucket,
    EXTRACT(HOUR FROM TO_TIMESTAMP(timestamp / 1000.0) AT TIME ZONE 'America/New_York') AS hour_et,
    EXTRACT(DOW FROM TO_TIMESTAMP(timestamp / 1000.0) AT TIME ZONE 'America/New_York') AS day_of_week,
    m.category,
    e.event_type,
    COUNT(*) AS event_count,
    COUNT(DISTINCT e.market_id) AS active_markets,
    AVG(CASE WHEN e.event_type = 'price_change' THEN ABS(e.new_value - COALESCE(e.old_value, e.new_value)) END) AS avg_price_delta,
    SUM(CASE WHEN e.event_type = 'trade' THEN 1 ELSE 0 END) AS trade_count
FROM events e
JOIN markets m ON m.id = e.market_id
WHERE e.timestamp > EXTRACT(EPOCH FROM NOW() - INTERVAL '7 days') * 1000
GROUP BY hour_bucket, hour_et, day_of_week, m.category, e.event_type;

CREATE INDEX IF NOT EXISTS idx_v_hourly_activity_hour
    ON v_hourly_activity(hour_et);
"""


class PostgresStore(BaseStore, LoggerMixin):
    """PostgreSQL-backed event store using asyncpg connection pooling."""

    def __init__(
        self,
        dsn: str,
        pool_min: int = 2,
        pool_max: int = 10,
    ) -> None:
        self._dsn = dsn
        self._pool_min = pool_min
        self._pool_max = pool_max
        self._pool: Optional[asyncpg.Pool] = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Store not initialized. Call initialize() first.")
        return self._pool

    async def initialize(self) -> None:
        """Create connection pool, tables, indexes, and materialized views."""
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=self._pool_min,
            max_size=self._pool_max,
        )
        async with self.pool.acquire() as conn:
            await conn.execute(_SCHEMA_SQL)
            # Add columns that may not exist on older schemas
            for col, typ in [("end_date", "TEXT"), ("volume", "DOUBLE PRECISION DEFAULT 0")]:
                try:
                    await conn.execute(
                        f"ALTER TABLE markets ADD COLUMN {col} {typ}"
                    )
                except asyncpg.DuplicateColumnError:
                    pass
            # Recreate views if schema has changed (e.g. new columns)
            try:
                await conn.fetchrow(
                    "SELECT description, end_date, rank_score, volume FROM v_current_market_state LIMIT 0"
                )
            except (asyncpg.UndefinedColumnError, asyncpg.UndefinedTableError):
                await conn.execute(
                    "DROP MATERIALIZED VIEW IF EXISTS v_current_market_state CASCADE"
                )
            # Ensure v_hourly_activity exists (added after initial deployment)
            try:
                await conn.fetchrow(
                    "SELECT hour_bucket FROM v_hourly_activity LIMIT 0"
                )
            except asyncpg.UndefinedTableError:
                pass  # Will be created by _VIEWS_SQL below
            # Materialized views — create only if they don't exist
            try:
                await conn.execute(_VIEWS_SQL)
            except asyncpg.DuplicateObjectError:
                pass  # views already exist
        self.logger.info("PostgreSQL store initialized", dsn=self._dsn.split("@")[-1])

    # ------------------------------------------------------------------
    # Markets
    # ------------------------------------------------------------------

    async def upsert_markets(self, markets: List[DiscoveredMarket]) -> int:
        """Insert or update markets. Returns count of newly inserted.

        Uses unnest-based batch INSERT for performance over remote
        connections (single round-trip per batch instead of N).
        """
        now_ms = int(time.time() * 1000)
        new_count = 0
        batch_size = 500

        sql = """
            INSERT INTO markets
                (platform, external_id, title, description, category,
                 end_date, is_active, first_seen_at, last_updated_at, volume)
            SELECT * FROM unnest(
                $1::text[], $2::text[], $3::text[], $4::text[], $5::text[],
                $6::text[], $7::bool[], $8::bigint[], $9::bigint[], $10::float8[]
            )
            ON CONFLICT (platform, external_id) DO UPDATE SET
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                category = EXCLUDED.category,
                end_date = EXCLUDED.end_date,
                is_active = EXCLUDED.is_active,
                last_updated_at = EXCLUDED.last_updated_at,
                volume = EXCLUDED.volume
            RETURNING
                CASE WHEN xmax = 0 THEN 1 ELSE 0 END
        """

        async with self.pool.acquire() as conn:
            for i in range(0, len(markets), batch_size):
                batch = markets[i : i + batch_size]
                platforms = [m.platform.value for m in batch]
                external_ids = [m.external_id for m in batch]
                titles = [m.title for m in batch]
                descriptions = [m.description for m in batch]
                categories = [m.category for m in batch]
                end_dates = [m.end_date for m in batch]
                actives = [m.is_active for m in batch]
                first_seen = [now_ms] * len(batch)
                last_updated = [now_ms] * len(batch)
                volumes = [m.volume or 0.0 for m in batch]

                rows = await conn.fetch(
                    sql,
                    platforms, external_ids, titles, descriptions,
                    categories, end_dates, actives, first_seen, last_updated,
                    volumes,
                )
                new_count += sum(1 for r in rows if r[0] == 1)

        return new_count

    async def get_market_by_external_id(
        self, platform: str, external_id: str
    ) -> Optional[MarketRecord]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM markets WHERE platform = $1 AND external_id = $2",
                platform,
                external_id,
            )
        return self._row_to_market(row) if row else None

    async def get_market_by_id(self, market_id: int) -> Optional[MarketRecord]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM markets WHERE id = $1", market_id
            )
        return self._row_to_market(row) if row else None

    async def deactivate_stale_markets(
        self, platform: str, before_ms: int
    ) -> int:
        sql = """
            UPDATE markets
            SET is_active = FALSE
            WHERE platform = $1
              AND is_active = TRUE
              AND last_updated_at < $2
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute(sql, platform, before_ms)
        # asyncpg returns e.g. "UPDATE 1234"
        return int(result.split()[-1])

    async def get_active_markets(
        self, platform: Optional[str] = None
    ) -> List[MarketRecord]:
        async with self.pool.acquire() as conn:
            if platform:
                rows = await conn.fetch(
                    "SELECT * FROM markets WHERE is_active = TRUE AND platform = $1",
                    platform,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM markets WHERE is_active = TRUE"
                )
        return [self._row_to_market(r) for r in rows]

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def insert_events(self, events: List[EventRecord]) -> int:
        """Batch-insert events using COPY for performance."""
        if not events:
            return 0

        records = [
            (
                e.market_id,
                e.event_type.value,
                e.old_value,
                e.new_value,
                e.metadata,
                e.timestamp,
            )
            for e in events
        ]

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(
                    """INSERT INTO events
                       (market_id, event_type, old_value, new_value, metadata, timestamp)
                       VALUES ($1, $2, $3, $4, $5, $6)""",
                    records,
                )
        return len(events)

    async def get_events(
        self,
        market_id: Optional[int] = None,
        event_type: Optional[str] = None,
        since: Optional[int] = None,
        limit: int = 1000,
    ) -> List[EventRecord]:
        clauses: list[str] = []
        params: list[object] = []
        idx = 1

        if market_id is not None:
            clauses.append(f"market_id = ${idx}")
            params.append(market_id)
            idx += 1
        if event_type is not None:
            clauses.append(f"event_type = ${idx}")
            params.append(event_type)
            idx += 1
        if since is not None:
            clauses.append(f"timestamp >= ${idx}")
            params.append(since)
            idx += 1

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM events {where} ORDER BY timestamp DESC LIMIT ${idx}"
        params.append(limit)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return [self._row_to_event(r) for r in rows]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def get_market_count(self) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM markets")

    async def get_event_count(self) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM events")

    async def get_event_time_range(self) -> Tuple[Optional[int], Optional[int]]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT MIN(timestamp), MAX(timestamp) FROM events"
            )
        if row and row[0] is not None:
            return (row[0], row[1])
        return (None, None)

    # ------------------------------------------------------------------
    # Data integrity queries (Milestone 1.3)
    # ------------------------------------------------------------------

    async def get_event_count_in_range(
        self, since: int, until: Optional[int] = None
    ) -> int:
        async with self.pool.acquire() as conn:
            if until is not None:
                return await conn.fetchval(
                    "SELECT COUNT(*) FROM events WHERE timestamp >= $1 AND timestamp <= $2",
                    since,
                    until,
                )
            return await conn.fetchval(
                "SELECT COUNT(*) FROM events WHERE timestamp >= $1",
                since,
            )

    async def get_duplicate_event_count(
        self, since: Optional[int] = None, until: Optional[int] = None
    ) -> int:
        clauses: list[str] = []
        params: list[object] = []
        idx = 1

        if since is not None:
            clauses.append(f"timestamp >= ${idx}")
            params.append(since)
            idx += 1
        if until is not None:
            clauses.append(f"timestamp <= ${idx}")
            params.append(until)
            idx += 1

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        query = f"""
            SELECT COALESCE(SUM(cnt - 1), 0) FROM (
                SELECT COUNT(*) as cnt
                FROM events {where}
                GROUP BY market_id, event_type, timestamp, new_value
                HAVING COUNT(*) > 1
            ) sub
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *params)

    async def get_event_gaps(
        self,
        gap_threshold_ms: int = 300_000,
        since: Optional[int] = None,
        until: Optional[int] = None,
    ) -> List[Tuple[int, int, int]]:
        clauses: list[str] = []
        params: list[object] = []
        idx = 1

        if since is not None:
            clauses.append(f"timestamp >= ${idx}")
            params.append(since)
            idx += 1
        if until is not None:
            clauses.append(f"timestamp <= ${idx}")
            params.append(until)
            idx += 1

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        query = f"""
            SELECT prev_ts, next_ts, (next_ts - prev_ts) as gap_ms FROM (
                SELECT
                    timestamp as prev_ts,
                    LEAD(timestamp) OVER (ORDER BY timestamp) as next_ts
                FROM events {where}
            ) gaps
            WHERE next_ts IS NOT NULL AND (next_ts - prev_ts) >= ${idx}
            ORDER BY prev_ts
        """
        params.append(gap_threshold_ms)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return [(row[0], row[1], row[2]) for row in rows]

    async def get_ordering_violations(
        self, since: Optional[int] = None, until: Optional[int] = None
    ) -> int:
        clauses: list[str] = []
        params: list[object] = []
        idx = 1

        if since is not None:
            clauses.append(f"e1.timestamp >= ${idx}")
            params.append(since)
            idx += 1
        if until is not None:
            clauses.append(f"e1.timestamp <= ${idx}")
            params.append(until)
            idx += 1

        where_extra = f"AND {' AND '.join(clauses)}" if clauses else ""

        query = f"""
            SELECT COUNT(*) FROM events e1
            INNER JOIN events e2 ON e2.id = e1.id - 1
            WHERE e1.timestamp < e2.timestamp {where_extra}
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *params)

    async def get_event_type_distribution(
        self, since: Optional[int] = None, until: Optional[int] = None
    ) -> Dict[str, int]:
        clauses: list[str] = []
        params: list[object] = []
        idx = 1

        if since is not None:
            clauses.append(f"timestamp >= ${idx}")
            params.append(since)
            idx += 1
        if until is not None:
            clauses.append(f"timestamp <= ${idx}")
            params.append(until)
            idx += 1

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        query = f"""
            SELECT event_type, COUNT(*) FROM events {where}
            GROUP BY event_type ORDER BY COUNT(*) DESC
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return {row[0]: row[1] for row in rows}

    # ------------------------------------------------------------------
    # Anomaly detection (Milestone 2.1)
    # ------------------------------------------------------------------

    async def get_events_in_window(
        self,
        market_id: int,
        event_type: str,
        window_start: int,
        window_end: int,
    ) -> List[EventRecord]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM events
                   WHERE market_id = $1 AND event_type = $2
                     AND timestamp >= $3 AND timestamp <= $4
                   ORDER BY timestamp ASC""",
                market_id,
                event_type,
                window_start,
                window_end,
            )
        return [self._row_to_event(r) for r in rows]

    async def insert_anomaly(
        self,
        anomaly: AnomalyRecord,
        market_links: List[AnomalyMarketRecord],
    ) -> int:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                anomaly_id = await conn.fetchval(
                    """INSERT INTO anomalies
                       (anomaly_type, severity, topic_cluster_id, market_count,
                        window_start, detected_at, summary, status, metadata)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                       RETURNING id""",
                    anomaly.anomaly_type.value,
                    anomaly.severity,
                    anomaly.topic_cluster_id,
                    anomaly.market_count,
                    anomaly.window_start,
                    anomaly.detected_at,
                    anomaly.summary,
                    anomaly.status.value,
                    anomaly.metadata,
                )

                for link in market_links:
                    await conn.execute(
                        """INSERT INTO anomaly_markets
                           (anomaly_id, market_id, price_delta, volume_ratio)
                           VALUES ($1, $2, $3, $4)""",
                        anomaly_id,
                        link.market_id,
                        link.price_delta,
                        link.volume_ratio,
                    )

        return anomaly_id

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
        clauses: list[str] = []
        params: list[object] = []
        idx = 1

        if since is not None:
            clauses.append(f"a.detected_at >= ${idx}")
            params.append(since)
            idx += 1
        if until is not None:
            clauses.append(f"a.detected_at <= ${idx}")
            params.append(until)
            idx += 1
        if status is not None:
            clauses.append(f"a.status = ${idx}")
            params.append(status.value)
            idx += 1
        if anomaly_type is not None:
            clauses.append(f"a.anomaly_type = ${idx}")
            params.append(anomaly_type)
            idx += 1
        if min_severity is not None:
            clauses.append(f"a.severity >= ${idx}")
            params.append(min_severity)
            idx += 1
        if market_id is not None:
            clauses.append(
                f"a.id IN (SELECT anomaly_id FROM anomaly_markets WHERE market_id = ${idx})"
            )
            params.append(market_id)
            idx += 1

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""SELECT a.* FROM anomalies a {where}
                    ORDER BY a.detected_at DESC LIMIT ${idx}"""
        params.append(limit)

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        return [self._row_to_anomaly(r) for r in rows]

    async def get_anomaly_markets(
        self, anomaly_id: int
    ) -> List[AnomalyMarketRecord]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM anomaly_markets WHERE anomaly_id = $1",
                anomaly_id,
            )
        return [self._row_to_anomaly_market(r) for r in rows]

    async def update_anomaly_status(
        self, anomaly_id: int, status: AnomalyStatus
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE anomalies SET status = $1 WHERE id = $2",
                status.value,
                anomaly_id,
            )

    async def update_anomaly_metadata(
        self, anomaly_id: int, metadata: str
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE anomalies SET metadata = $1 WHERE id = $2",
                metadata,
                anomaly_id,
            )

    async def get_markets_with_active_anomalies(self) -> set[int]:
        """Get IDs of all markets that have at least one active anomaly."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT DISTINCT am.market_id
                   FROM anomaly_markets am
                   JOIN anomalies a ON a.id = am.anomaly_id
                   WHERE a.status = $1""",
                AnomalyStatus.ACTIVE.value,
            )
        return {row[0] for row in rows}

    async def expire_old_anomalies(self, older_than: int) -> int:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """UPDATE anomalies SET status = $1
                   WHERE status = $2 AND detected_at < $3""",
                AnomalyStatus.EXPIRED.value,
                AnomalyStatus.ACTIVE.value,
                older_than,
            )
        # asyncpg returns "UPDATE N" string
        return int(result.split()[-1])

    # ------------------------------------------------------------------
    # Topic clustering (Milestone 2.2)
    # ------------------------------------------------------------------

    async def insert_cluster(self, cluster: TopicCluster) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                """INSERT INTO topic_clusters (name, description, created_at, updated_at)
                   VALUES ($1, $2, $3, $4)
                   RETURNING id""",
                cluster.name,
                cluster.description,
                cluster.created_at,
                cluster.updated_at,
            )

    async def get_clusters(self) -> List[TopicCluster]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM topic_clusters ORDER BY name"
            )
        return [self._row_to_cluster(r) for r in rows]

    async def get_cluster_by_name(self, name: str) -> Optional[TopicCluster]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM topic_clusters WHERE name = $1", name
            )
        return self._row_to_cluster(row) if row else None

    async def assign_market_to_cluster(
        self, market_id: int, cluster_id: int, confidence: float
    ) -> None:
        now_ms = int(time.time() * 1000)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO market_cluster_memberships
                   (market_id, cluster_id, confidence, assigned_at)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (market_id, cluster_id) DO UPDATE SET
                       confidence = EXCLUDED.confidence,
                       assigned_at = EXCLUDED.assigned_at""",
                market_id,
                cluster_id,
                confidence,
                now_ms,
            )

    async def get_cluster_markets(
        self, cluster_id: int
    ) -> List[Tuple[int, float]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT market_id, confidence FROM market_cluster_memberships WHERE cluster_id = $1",
                cluster_id,
            )
        return [(row[0], row[1]) for row in rows]

    async def get_market_clusters(
        self, market_id: int
    ) -> List[Tuple[int, str, float]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT tc.id, tc.name, mcm.confidence
                   FROM market_cluster_memberships mcm
                   JOIN topic_clusters tc ON tc.id = mcm.cluster_id
                   WHERE mcm.market_id = $1""",
                market_id,
            )
        return [(row[0], row[1], row[2]) for row in rows]

    async def get_unassigned_markets(self) -> List[MarketRecord]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT m.* FROM markets m
                   LEFT JOIN market_cluster_memberships mcm ON m.id = mcm.market_id
                   WHERE m.is_active = TRUE AND mcm.market_id IS NULL"""
            )
        return [self._row_to_market(r) for r in rows]

    async def count_unassigned_markets(self) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                """SELECT COUNT(*) FROM markets m
                   LEFT JOIN market_cluster_memberships mcm ON m.id = mcm.market_id
                   WHERE m.is_active = TRUE AND mcm.market_id IS NULL"""
            )

    # ------------------------------------------------------------------
    # Cross-platform links (Milestone 3.3)
    # ------------------------------------------------------------------

    async def upsert_cross_platform_link(self, link: CrossPlatformLink) -> int:
        a, b = sorted([link.market_id_a, link.market_id_b])
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO cross_platform_links
                   (market_id_a, market_id_b, confidence, method, created_at)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (market_id_a, market_id_b) DO UPDATE
                   SET confidence = EXCLUDED.confidence,
                       method = EXCLUDED.method,
                       created_at = EXCLUDED.created_at
                   RETURNING id""",
                a, b, link.confidence, link.method, link.created_at,
            )
        return row["id"]

    async def get_cross_platform_links(
        self, market_id: Optional[int] = None
    ) -> List[CrossPlatformLink]:
        async with self.pool.acquire() as conn:
            if market_id is not None:
                rows = await conn.fetch(
                    """SELECT * FROM cross_platform_links
                       WHERE market_id_a = $1 OR market_id_b = $1
                       ORDER BY confidence DESC""",
                    market_id,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM cross_platform_links ORDER BY confidence DESC"
                )
        return [self._row_to_cross_platform_link(r) for r in rows]

    async def get_cross_platform_pair(
        self, market_id_a: int, market_id_b: int
    ) -> Optional[CrossPlatformLink]:
        a, b = sorted([market_id_a, market_id_b])
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM cross_platform_links WHERE market_id_a = $1 AND market_id_b = $2",
                a, b,
            )
        return self._row_to_cross_platform_link(row) if row else None

    # ------------------------------------------------------------------
    # Market lifecycle (resolution detection)
    # ------------------------------------------------------------------

    async def deactivate_market(self, market_id: int) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE markets SET is_active = FALSE WHERE id = $1 AND is_active = TRUE",
                market_id,
            )
        return int(result.split()[-1]) > 0

    async def deactivate_expired_markets(self, now_iso: str) -> int:
        from datetime import datetime

        now_dt = datetime.fromisoformat(now_iso)
        sql = """
            UPDATE markets SET is_active = FALSE
            WHERE is_active = TRUE
              AND end_date IS NOT NULL AND end_date != ''
              AND end_date::timestamptz <= $1
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute(sql, now_dt)
        return int(result.split()[-1])

    # ------------------------------------------------------------------
    # Targeted queries
    # ------------------------------------------------------------------

    async def get_markets_with_recent_events(
        self, since_ms: int
    ) -> List[int]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT market_id FROM events WHERE timestamp >= $1",
                since_ms,
            )
        return [row[0] for row in rows]

    # ------------------------------------------------------------------
    # Data retention (Milestone 3.3)
    # ------------------------------------------------------------------

    async def prune_events(self, older_than: int) -> int:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM events WHERE timestamp < $1", older_than
            )
        # asyncpg returns "DELETE N"
        return int(result.split()[-1])

    # ------------------------------------------------------------------
    # Materialized view queries (Phase 4 sync layer)
    # ------------------------------------------------------------------

    async def query_market_state(self, with_events_only: bool = False) -> List[dict]:
        """Read v_current_market_state for sync.

        Args:
            with_events_only: If True, only return markets that have at least
                one event (price or volume). Dramatically reduces result set
                from 144K+ discovered markets to the ~200 actually tracked.
        """
        async with self.pool.acquire() as conn:
            if with_events_only:
                rows = await conn.fetch(
                    """SELECT * FROM v_current_market_state
                       WHERE last_price IS NOT NULL
                          OR last_volume IS NOT NULL"""
                )
            else:
                rows = await conn.fetch("SELECT * FROM v_current_market_state")
        return [dict(r) for r in rows]

    async def query_active_anomalies(self) -> List[dict]:
        """Read v_active_anomalies for sync."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM v_active_anomalies")
        return [dict(r) for r in rows]

    async def query_trending_topics(self) -> List[dict]:
        """Read v_trending_topics for sync."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM v_trending_topics")
        return [dict(r) for r in rows]

    async def query_market_summaries(self) -> List[dict]:
        """Read v_market_summaries for sync — only markets with events."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM v_market_summaries WHERE event_count > 0"
            )
        return [dict(r) for r in rows]

    async def query_hourly_activity(
        self, hours: int = 168
    ) -> List[dict]:
        """Read v_hourly_activity for trend analysis."""
        since_ms = int((time.time() - hours * 3600) * 1000)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM v_hourly_activity WHERE hour_bucket >= $1 ORDER BY hour_bucket",
                since_ms,
            )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Materialized view management
    # ------------------------------------------------------------------

    async def refresh_view(
        self, view_name: str, concurrently: bool = True
    ) -> None:
        """Refresh a single materialized view."""
        if view_name not in _MATERIALIZED_VIEWS:
            raise ValueError(f"Unknown materialized view: {view_name}")
        modifier = "CONCURRENTLY" if concurrently else ""
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"REFRESH MATERIALIZED VIEW {modifier} {view_name}"
            )
        self.logger.debug("view_refreshed", view=view_name)

    async def refresh_views(self, concurrently: bool = True) -> None:
        """Refresh all materialized views."""
        for view in _MATERIALIZED_VIEWS:
            await self.refresh_view(view, concurrently=concurrently)
        self.logger.info("Materialized views refreshed", concurrently=concurrently)

    # ------------------------------------------------------------------
    # Candlestick aggregation (Feature C)
    # ------------------------------------------------------------------

    async def compute_candlesticks(
        self,
        market_id: int,
        period_minutes: int = 60,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
    ) -> List[dict]:
        """Compute OHLCV candlesticks from stored price_change events.

        Uses SQL window functions to aggregate events into time buckets.
        Each candle has open, high, low, close (from price), and volume
        (from volume_update events in the same bucket).

        Args:
            market_id: Internal market ID.
            period_minutes: Candle width in minutes (default 60).
            start_ts: Start timestamp (Unix ms). Defaults to 24h ago.
            end_ts: End timestamp (Unix ms). Defaults to now.

        Returns:
            List of dicts with keys: time, open, high, low, close, volume.
        """
        import time as _time

        now_ms = int(_time.time() * 1000)
        if end_ts is None:
            end_ts = now_ms
        if start_ts is None:
            start_ts = now_ms - 86_400_000  # 24 hours

        period_ms = period_minutes * 60 * 1000

        query = """
            WITH price_events AS (
                SELECT
                    timestamp,
                    new_value AS price,
                    (timestamp / $4) AS bucket
                FROM events
                WHERE market_id = $1
                  AND event_type = 'price_change'
                  AND timestamp >= $2
                  AND timestamp <= $3
                  AND new_value > 0
            ),
            volume_events AS (
                SELECT
                    (timestamp / $4) AS bucket,
                    SUM(new_value) AS total_volume
                FROM events
                WHERE market_id = $1
                  AND event_type IN ('trade', 'volume_update')
                  AND timestamp >= $2
                  AND timestamp <= $3
                GROUP BY (timestamp / $4)
            ),
            bucketed AS (
                SELECT
                    bucket,
                    MIN(timestamp) AS first_ts,
                    MAX(timestamp) AS last_ts,
                    MIN(price) AS low,
                    MAX(price) AS high,
                    COUNT(*) AS tick_count
                FROM price_events
                GROUP BY bucket
            ),
            with_open_close AS (
                SELECT
                    b.bucket,
                    b.first_ts,
                    b.low,
                    b.high,
                    b.tick_count,
                    p_open.price AS open_price,
                    p_close.price AS close_price
                FROM bucketed b
                JOIN price_events p_open
                    ON p_open.bucket = b.bucket AND p_open.timestamp = b.first_ts
                JOIN price_events p_close
                    ON p_close.bucket = b.bucket AND p_close.timestamp = b.last_ts
            )
            SELECT
                (oc.bucket * $4 / 1000)::BIGINT AS time_sec,
                oc.open_price AS open,
                oc.high,
                oc.low,
                oc.close_price AS close,
                COALESCE(v.total_volume, 0) AS volume
            FROM with_open_close oc
            LEFT JOIN volume_events v ON v.bucket = oc.bucket
            ORDER BY oc.bucket ASC
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, market_id, start_ts, end_ts, period_ms)

        return [
            {
                "time": int(r["time_sec"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r["volume"]),
            }
            for r in rows
        ]

    async def get_series_markets(
        self, series_prefix: str
    ) -> List[MarketRecord]:
        """Get all active markets whose external_id starts with a series prefix.

        Kalshi tickers follow SERIES-OUTCOME format, so this groups all
        outcomes for a series (e.g., all BTC daily price markets).
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM markets
                   WHERE external_id LIKE $1 || '-%'
                     AND is_active = TRUE
                   ORDER BY external_id""",
                series_prefix,
            )
        return [self._row_to_market(r) for r in rows]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    # ------------------------------------------------------------------
    # Row mapping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_market(row: asyncpg.Record) -> MarketRecord:
        return MarketRecord(
            id=row["id"],
            platform=Platform(row["platform"]),
            external_id=row["external_id"],
            title=row["title"],
            description=row["description"],
            category=row["category"],
            is_active=bool(row["is_active"]),
            first_seen_at=row["first_seen_at"],
            last_updated_at=row["last_updated_at"],
        )

    @staticmethod
    def _row_to_event(row: asyncpg.Record) -> EventRecord:
        return EventRecord(
            id=row["id"],
            market_id=row["market_id"],
            event_type=EventType(row["event_type"]),
            old_value=row["old_value"],
            new_value=row["new_value"],
            metadata=row["metadata"],
            timestamp=row["timestamp"],
        )

    @staticmethod
    def _row_to_anomaly(row: asyncpg.Record) -> AnomalyRecord:
        return AnomalyRecord(
            id=row["id"],
            anomaly_type=AnomalyType(row["anomaly_type"]),
            severity=row["severity"],
            topic_cluster_id=row["topic_cluster_id"],
            market_count=row["market_count"],
            window_start=row["window_start"],
            detected_at=row["detected_at"],
            summary=row["summary"],
            status=AnomalyStatus(row["status"]),
            metadata=row["metadata"],
        )

    @staticmethod
    def _row_to_anomaly_market(row: asyncpg.Record) -> AnomalyMarketRecord:
        return AnomalyMarketRecord(
            anomaly_id=row["anomaly_id"],
            market_id=row["market_id"],
            price_delta=row["price_delta"],
            volume_ratio=row["volume_ratio"],
        )

    @staticmethod
    def _row_to_cluster(row: asyncpg.Record) -> TopicCluster:
        return TopicCluster(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_cross_platform_link(row: asyncpg.Record) -> CrossPlatformLink:
        return CrossPlatformLink(
            id=row["id"],
            market_id_a=row["market_id_a"],
            market_id_b=row["market_id_b"],
            confidence=row["confidence"],
            method=row["method"],
            created_at=row["created_at"],
        )
