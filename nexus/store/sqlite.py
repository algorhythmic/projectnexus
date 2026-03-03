"""SQLite event store implementation using aiosqlite."""

import json
import time
from pathlib import Path
from typing import List, Optional

import aiosqlite

from nexus.core.logging import LoggerMixin
from nexus.core.types import (
    DiscoveredMarket,
    EventRecord,
    EventType,
    MarketRecord,
    Platform,
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
