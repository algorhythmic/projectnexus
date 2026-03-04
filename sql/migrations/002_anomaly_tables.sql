-- Migration 002: Anomaly Detection Tables (Milestone 2.1)
-- Adds tables for topic clusters, anomaly records, and junction tables.

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
