"""SQLite event store implementation using aiosqlite."""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiosqlite

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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    category TEXT,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    first_seen_at INTEGER NOT NULL,
    last_updated_at INTEGER NOT NULL,
    UNIQUE(platform, external_id)
);

CREATE INDEX IF NOT EXISTS idx_markets_platform ON markets(platform);
CREATE INDEX IF NOT EXISTS idx_markets_category ON markets(category);
CREATE INDEX IF NOT EXISTS idx_markets_is_active ON markets(is_active);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    old_value REAL,
    new_value REAL NOT NULL,
    metadata TEXT,
    timestamp INTEGER NOT NULL,
    FOREIGN KEY (market_id) REFERENCES markets(id)
);

CREATE INDEX IF NOT EXISTS idx_events_market_id ON events(market_id);
CREATE INDEX IF NOT EXISTS idx_events_event_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);

-- Phase 2: Anomaly Detection Tables

CREATE TABLE IF NOT EXISTS topic_clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS market_cluster_memberships (
    market_id INTEGER NOT NULL,
    cluster_id INTEGER NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    assigned_at INTEGER NOT NULL,
    PRIMARY KEY (market_id, cluster_id),
    FOREIGN KEY (market_id) REFERENCES markets(id),
    FOREIGN KEY (cluster_id) REFERENCES topic_clusters(id)
);

CREATE TABLE IF NOT EXISTS anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anomaly_type TEXT NOT NULL,
    severity REAL NOT NULL,
    topic_cluster_id INTEGER,
    market_count INTEGER NOT NULL,
    window_start INTEGER NOT NULL,
    detected_at INTEGER NOT NULL,
    summary TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    metadata TEXT,
    FOREIGN KEY (topic_cluster_id) REFERENCES topic_clusters(id)
);

CREATE INDEX IF NOT EXISTS idx_anomalies_detected_at ON anomalies(detected_at);
CREATE INDEX IF NOT EXISTS idx_anomalies_status ON anomalies(status);
CREATE INDEX IF NOT EXISTS idx_anomalies_severity ON anomalies(severity);

CREATE TABLE IF NOT EXISTS anomaly_markets (
    anomaly_id INTEGER NOT NULL,
    market_id INTEGER NOT NULL,
    price_delta REAL,
    volume_ratio REAL,
    PRIMARY KEY (anomaly_id, market_id),
    FOREIGN KEY (anomaly_id) REFERENCES anomalies(id),
    FOREIGN KEY (market_id) REFERENCES markets(id)
);

CREATE INDEX IF NOT EXISTS idx_anomaly_markets_market_id ON anomaly_markets(market_id);

-- Phase 3: Cross-platform links (Milestone 3.3)

CREATE TABLE IF NOT EXISTS cross_platform_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id_a INTEGER NOT NULL,
    market_id_b INTEGER NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    method TEXT NOT NULL DEFAULT 'cluster',
    created_at INTEGER NOT NULL,
    UNIQUE(market_id_a, market_id_b),
    FOREIGN KEY (market_id_a) REFERENCES markets(id),
    FOREIGN KEY (market_id_b) REFERENCES markets(id)
);

CREATE INDEX IF NOT EXISTS idx_cross_platform_links_a ON cross_platform_links(market_id_a);
CREATE INDEX IF NOT EXISTS idx_cross_platform_links_b ON cross_platform_links(market_id_b);
"""


class SQLiteStore(BaseStore, LoggerMixin):
    """SQLite-backed event store.

    Uses WAL mode for concurrent read/write and PRAGMA foreign_keys
    for referential integrity.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        """Create database file, enable WAL, and run schema DDL."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(_SCHEMA_SQL)
        await self._db.commit()
        self.logger.info("SQLite store initialized", path=self._db_path)

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Store not initialized. Call initialize() first.")
        return self._db

    # ------------------------------------------------------------------
    # Markets
    # ------------------------------------------------------------------

    async def deactivate_stale_markets(
        self, platform: str, before_ms: int
    ) -> int:
        cursor = await self.db.execute(
            """UPDATE markets
               SET is_active = 0
               WHERE platform = ? AND is_active = 1 AND last_updated_at < ?""",
            (platform, before_ms),
        )
        await self.db.commit()
        return cursor.rowcount

    async def upsert_markets(self, markets: List[DiscoveredMarket]) -> int:
        """Insert or update markets. Returns count of newly inserted."""
        now_ms = int(time.time() * 1000)
        new_count = 0

        for m in markets:
            cursor = await self.db.execute(
                "SELECT id FROM markets WHERE platform = ? AND external_id = ?",
                (m.platform.value, m.external_id),
            )
            existing = await cursor.fetchone()

            if existing is None:
                await self.db.execute(
                    """INSERT INTO markets
                       (platform, external_id, title, description, category,
                        is_active, first_seen_at, last_updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        m.platform.value,
                        m.external_id,
                        m.title,
                        m.description,
                        m.category,
                        m.is_active,
                        now_ms,
                        now_ms,
                    ),
                )
                new_count += 1
            else:
                await self.db.execute(
                    """UPDATE markets
                       SET title = ?, description = ?, category = ?,
                           is_active = ?, last_updated_at = ?
                       WHERE platform = ? AND external_id = ?""",
                    (
                        m.title,
                        m.description,
                        m.category,
                        m.is_active,
                        now_ms,
                        m.platform.value,
                        m.external_id,
                    ),
                )

        await self.db.commit()
        return new_count

    async def get_market_by_external_id(
        self, platform: str, external_id: str
    ) -> Optional[MarketRecord]:
        cursor = await self.db.execute(
            "SELECT * FROM markets WHERE platform = ? AND external_id = ?",
            (platform, external_id),
        )
        row = await cursor.fetchone()
        return self._row_to_market(row) if row else None

    async def get_active_markets(
        self, platform: Optional[str] = None
    ) -> List[MarketRecord]:
        if platform:
            cursor = await self.db.execute(
                "SELECT * FROM markets WHERE is_active = 1 AND platform = ?",
                (platform,),
            )
        else:
            cursor = await self.db.execute(
                "SELECT * FROM markets WHERE is_active = 1"
            )
        rows = await cursor.fetchall()
        return [self._row_to_market(r) for r in rows]

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def insert_events(self, events: List[EventRecord]) -> int:
        """Batch-insert events in a single transaction."""
        if not events:
            return 0
        await self.db.executemany(
            """INSERT INTO events
               (market_id, event_type, old_value, new_value, metadata, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [
                (
                    e.market_id,
                    e.event_type.value,
                    e.old_value,
                    e.new_value,
                    e.metadata,
                    e.timestamp,
                )
                for e in events
            ],
        )
        await self.db.commit()
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

        if market_id is not None:
            clauses.append("market_id = ?")
            params.append(market_id)
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"SELECT * FROM events {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [self._row_to_event(r) for r in rows]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def get_market_count(self) -> int:
        cursor = await self.db.execute("SELECT COUNT(*) FROM markets")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_event_count(self) -> int:
        cursor = await self.db.execute("SELECT COUNT(*) FROM events")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_event_time_range(self) -> Tuple[Optional[int], Optional[int]]:
        cursor = await self.db.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM events"
        )
        row = await cursor.fetchone()
        if row and row[0] is not None:
            return (row[0], row[1])
        return (None, None)

    # ------------------------------------------------------------------
    # Data integrity queries (Milestone 1.3)
    # ------------------------------------------------------------------

    async def get_event_count_in_range(
        self, since: int, until: Optional[int] = None
    ) -> int:
        if until is not None:
            cursor = await self.db.execute(
                "SELECT COUNT(*) FROM events WHERE timestamp >= ? AND timestamp <= ?",
                (since, until),
            )
        else:
            cursor = await self.db.execute(
                "SELECT COUNT(*) FROM events WHERE timestamp >= ?",
                (since,),
            )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_duplicate_event_count(
        self, since: Optional[int] = None, until: Optional[int] = None
    ) -> int:
        clauses: list[str] = []
        params: list[object] = []
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until is not None:
            clauses.append("timestamp <= ?")
            params.append(until)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        query = f"""
            SELECT COALESCE(SUM(cnt - 1), 0) FROM (
                SELECT COUNT(*) as cnt
                FROM events {where}
                GROUP BY market_id, event_type, timestamp, new_value
                HAVING COUNT(*) > 1
            )
        """
        cursor = await self.db.execute(query, params)
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_event_gaps(
        self,
        gap_threshold_ms: int = 300_000,
        since: Optional[int] = None,
        until: Optional[int] = None,
    ) -> List[Tuple[int, int, int]]:
        clauses: list[str] = []
        params: list[object] = []
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until is not None:
            clauses.append("timestamp <= ?")
            params.append(until)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        # Use LEAD() window function for efficient gap detection
        query = f"""
            SELECT prev_ts, next_ts, (next_ts - prev_ts) as gap_ms FROM (
                SELECT
                    timestamp as prev_ts,
                    LEAD(timestamp) OVER (ORDER BY timestamp) as next_ts
                FROM events {where}
            )
            WHERE next_ts IS NOT NULL AND (next_ts - prev_ts) >= ?
            ORDER BY prev_ts
        """
        params.append(gap_threshold_ms)
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [(row[0], row[1], row[2]) for row in rows]

    async def get_ordering_violations(
        self, since: Optional[int] = None, until: Optional[int] = None
    ) -> int:
        clauses: list[str] = []
        params: list[object] = []
        if since is not None:
            clauses.append("e1.timestamp >= ?")
            params.append(since)
        if until is not None:
            clauses.append("e1.timestamp <= ?")
            params.append(until)
        where_extra = f"AND {' AND '.join(clauses)}" if clauses else ""

        query = f"""
            SELECT COUNT(*) FROM events e1
            INNER JOIN events e2 ON e2.id = e1.id - 1
            WHERE e1.timestamp < e2.timestamp {where_extra}
        """
        cursor = await self.db.execute(query, params)
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_event_type_distribution(
        self, since: Optional[int] = None, until: Optional[int] = None
    ) -> Dict[str, int]:
        clauses: list[str] = []
        params: list[object] = []
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until is not None:
            clauses.append("timestamp <= ?")
            params.append(until)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        query = f"""
            SELECT event_type, COUNT(*) FROM events {where}
            GROUP BY event_type ORDER BY COUNT(*) DESC
        """
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
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
        cursor = await self.db.execute(
            """SELECT * FROM events
               WHERE market_id = ? AND event_type = ?
                 AND timestamp >= ? AND timestamp <= ?
               ORDER BY timestamp ASC""",
            (market_id, event_type, window_start, window_end),
        )
        rows = await cursor.fetchall()
        return [self._row_to_event(r) for r in rows]

    async def insert_anomaly(
        self,
        anomaly: AnomalyRecord,
        market_links: List[AnomalyMarketRecord],
    ) -> int:
        cursor = await self.db.execute(
            """INSERT INTO anomalies
               (anomaly_type, severity, topic_cluster_id, market_count,
                window_start, detected_at, summary, status, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                anomaly.anomaly_type.value,
                anomaly.severity,
                anomaly.topic_cluster_id,
                anomaly.market_count,
                anomaly.window_start,
                anomaly.detected_at,
                anomaly.summary,
                anomaly.status.value,
                anomaly.metadata,
            ),
        )
        anomaly_id = cursor.lastrowid

        for link in market_links:
            await self.db.execute(
                """INSERT INTO anomaly_markets
                   (anomaly_id, market_id, price_delta, volume_ratio)
                   VALUES (?, ?, ?, ?)""",
                (anomaly_id, link.market_id, link.price_delta, link.volume_ratio),
            )

        await self.db.commit()
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

        if since is not None:
            clauses.append("a.detected_at >= ?")
            params.append(since)
        if until is not None:
            clauses.append("a.detected_at <= ?")
            params.append(until)
        if status is not None:
            clauses.append("a.status = ?")
            params.append(status.value)
        if anomaly_type is not None:
            clauses.append("a.anomaly_type = ?")
            params.append(anomaly_type)
        if min_severity is not None:
            clauses.append("a.severity >= ?")
            params.append(min_severity)

        if market_id is not None:
            clauses.append(
                "a.id IN (SELECT anomaly_id FROM anomaly_markets WHERE market_id = ?)"
            )
            params.append(market_id)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""SELECT a.* FROM anomalies a {where}
                    ORDER BY a.detected_at DESC LIMIT ?"""
        params.append(limit)

        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [self._row_to_anomaly(r) for r in rows]

    async def get_anomaly_markets(
        self, anomaly_id: int
    ) -> List[AnomalyMarketRecord]:
        cursor = await self.db.execute(
            "SELECT * FROM anomaly_markets WHERE anomaly_id = ?",
            (anomaly_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_anomaly_market(r) for r in rows]

    async def update_anomaly_status(
        self, anomaly_id: int, status: AnomalyStatus
    ) -> None:
        await self.db.execute(
            "UPDATE anomalies SET status = ? WHERE id = ?",
            (status.value, anomaly_id),
        )
        await self.db.commit()

    async def expire_old_anomalies(self, older_than: int) -> int:
        cursor = await self.db.execute(
            """UPDATE anomalies SET status = ?
               WHERE status = ? AND detected_at < ?""",
            (AnomalyStatus.EXPIRED.value, AnomalyStatus.ACTIVE.value, older_than),
        )
        await self.db.commit()
        return cursor.rowcount

    # ------------------------------------------------------------------
    # Topic clustering (Milestone 2.2)
    # ------------------------------------------------------------------

    async def insert_cluster(self, cluster: TopicCluster) -> int:
        cursor = await self.db.execute(
            """INSERT INTO topic_clusters (name, description, created_at, updated_at)
               VALUES (?, ?, ?, ?)""",
            (cluster.name, cluster.description, cluster.created_at, cluster.updated_at),
        )
        await self.db.commit()
        return cursor.lastrowid

    async def get_clusters(self) -> List[TopicCluster]:
        cursor = await self.db.execute(
            "SELECT * FROM topic_clusters ORDER BY name"
        )
        rows = await cursor.fetchall()
        return [self._row_to_cluster(r) for r in rows]

    async def get_cluster_by_name(self, name: str) -> Optional[TopicCluster]:
        cursor = await self.db.execute(
            "SELECT * FROM topic_clusters WHERE name = ?", (name,)
        )
        row = await cursor.fetchone()
        return self._row_to_cluster(row) if row else None

    async def assign_market_to_cluster(
        self, market_id: int, cluster_id: int, confidence: float
    ) -> None:
        now_ms = int(time.time() * 1000)
        await self.db.execute(
            """INSERT OR REPLACE INTO market_cluster_memberships
               (market_id, cluster_id, confidence, assigned_at)
               VALUES (?, ?, ?, ?)""",
            (market_id, cluster_id, confidence, now_ms),
        )
        await self.db.commit()

    async def get_cluster_markets(
        self, cluster_id: int
    ) -> List[Tuple[int, float]]:
        cursor = await self.db.execute(
            "SELECT market_id, confidence FROM market_cluster_memberships WHERE cluster_id = ?",
            (cluster_id,),
        )
        rows = await cursor.fetchall()
        return [(row[0], row[1]) for row in rows]

    async def get_market_clusters(
        self, market_id: int
    ) -> List[Tuple[int, str, float]]:
        cursor = await self.db.execute(
            """SELECT tc.id, tc.name, mcm.confidence
               FROM market_cluster_memberships mcm
               JOIN topic_clusters tc ON tc.id = mcm.cluster_id
               WHERE mcm.market_id = ?""",
            (market_id,),
        )
        rows = await cursor.fetchall()
        return [(row[0], row[1], row[2]) for row in rows]

    async def get_unassigned_markets(self) -> List[MarketRecord]:
        cursor = await self.db.execute(
            """SELECT m.* FROM markets m
               LEFT JOIN market_cluster_memberships mcm ON m.id = mcm.market_id
               WHERE m.is_active = 1 AND mcm.market_id IS NULL"""
        )
        rows = await cursor.fetchall()
        return [self._row_to_market(r) for r in rows]

    # ------------------------------------------------------------------
    # Cross-platform links (Milestone 3.3)
    # ------------------------------------------------------------------

    async def upsert_cross_platform_link(self, link: CrossPlatformLink) -> int:
        # Normalize ordering: lower market_id first
        a, b = sorted([link.market_id_a, link.market_id_b])
        cursor = await self.db.execute(
            """INSERT OR REPLACE INTO cross_platform_links
               (market_id_a, market_id_b, confidence, method, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (a, b, link.confidence, link.method, link.created_at),
        )
        await self.db.commit()
        return cursor.lastrowid

    async def get_cross_platform_links(
        self, market_id: Optional[int] = None
    ) -> List[CrossPlatformLink]:
        if market_id is not None:
            cursor = await self.db.execute(
                """SELECT * FROM cross_platform_links
                   WHERE market_id_a = ? OR market_id_b = ?
                   ORDER BY confidence DESC""",
                (market_id, market_id),
            )
        else:
            cursor = await self.db.execute(
                "SELECT * FROM cross_platform_links ORDER BY confidence DESC"
            )
        rows = await cursor.fetchall()
        return [self._row_to_cross_platform_link(r) for r in rows]

    async def get_cross_platform_pair(
        self, market_id_a: int, market_id_b: int
    ) -> Optional[CrossPlatformLink]:
        a, b = sorted([market_id_a, market_id_b])
        cursor = await self.db.execute(
            "SELECT * FROM cross_platform_links WHERE market_id_a = ? AND market_id_b = ?",
            (a, b),
        )
        row = await cursor.fetchone()
        return self._row_to_cross_platform_link(row) if row else None

    # ------------------------------------------------------------------
    # Data retention (Milestone 3.3)
    # ------------------------------------------------------------------

    async def prune_events(self, older_than: int) -> int:
        cursor = await self.db.execute(
            "DELETE FROM events WHERE timestamp < ?", (older_than,)
        )
        await self.db.commit()
        return cursor.rowcount

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_market(row: aiosqlite.Row) -> MarketRecord:
        return MarketRecord(
            id=row[0],
            platform=Platform(row[1]),
            external_id=row[2],
            title=row[3],
            description=row[4],
            category=row[5],
            is_active=bool(row[6]),
            first_seen_at=row[7],
            last_updated_at=row[8],
        )

    @staticmethod
    def _row_to_event(row: aiosqlite.Row) -> EventRecord:
        return EventRecord(
            id=row[0],
            market_id=row[1],
            event_type=EventType(row[2]),
            old_value=row[3],
            new_value=row[4],
            metadata=row[5],
            timestamp=row[6],
        )

    @staticmethod
    def _row_to_anomaly(row: aiosqlite.Row) -> AnomalyRecord:
        return AnomalyRecord(
            id=row[0],
            anomaly_type=AnomalyType(row[1]),
            severity=row[2],
            topic_cluster_id=row[3],
            market_count=row[4],
            window_start=row[5],
            detected_at=row[6],
            summary=row[7],
            status=AnomalyStatus(row[8]),
            metadata=row[9],
        )

    @staticmethod
    def _row_to_cluster(row: aiosqlite.Row) -> TopicCluster:
        return TopicCluster(
            id=row[0],
            name=row[1],
            description=row[2],
            created_at=row[3],
            updated_at=row[4],
        )

    @staticmethod
    def _row_to_anomaly_market(row: aiosqlite.Row) -> AnomalyMarketRecord:
        return AnomalyMarketRecord(
            anomaly_id=row[0],
            market_id=row[1],
            price_delta=row[2],
            volume_ratio=row[3],
        )

    @staticmethod
    def _row_to_cross_platform_link(row: aiosqlite.Row) -> CrossPlatformLink:
        return CrossPlatformLink(
            id=row[0],
            market_id_a=row[1],
            market_id_b=row[2],
            confidence=row[3],
            method=row[4],
            created_at=row[5],
        )
