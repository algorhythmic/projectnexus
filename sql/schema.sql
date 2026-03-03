-- Nexus Event Store Schema (Phase 1: SQLite)
--
-- Tables: markets, events
-- Phase 2+ tables (topic_clusters, market_cluster_memberships,
-- anomalies, anomaly_markets) are defined in migrations/.

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
