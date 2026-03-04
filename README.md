# Nexus

Real-time prediction market intelligence engine.

Nexus ingests streaming data from prediction market platforms (Kalshi, Polymarket), detects anomalous price and volume movements, identifies correlated shifts across semantically related markets, and surfaces structured alerts for human decision-making.

## Project Status

### Phase 1 — Foundation: Single-Platform Ingestion

| Milestone | Status | Description |
|-----------|--------|-------------|
| 1.1 — Project Scaffolding | Done | Kalshi REST adapter with RSA-PSS auth, SQLite event store, market discovery loop, CLI |
| 1.2 — Kalshi WebSocket Adapter | Done | WebSocket streaming with auto-reconnect, event bus with batch drain, ingestion manager |
| 1.3 — Stability Testing | Done | Data integrity validation, gap/duplicate/ordering checks, Decision Gate CLI |

**Decision Gate: PASSED** — 72h+ stable ingestion, 100K+ events, failure modes documented.

### Phase 2 — Analytics: Anomaly Detection

| Milestone | Status | Description |
|-----------|--------|-------------|
| 2.1 — Windowed Anomaly Detection | Done | Sliding windows (5/15/60/1440 min), three detection rules (price threshold, volume spike, Z-score), anomaly tables and CRUD |
| 2.2 — Topic Graph Construction | Done | LLM-powered semantic clustering via Claude, batch and incremental modes, cluster management CLI |
| 2.3 — Correlation Detection | Done | Cross-market cluster correlation, direction detection, deduplication, signal analysis reporting |

**Decision Gate: IN PROGRESS** — Requires one-week live validation (< 50 alerts/day, > 60% catalyst correlation).

### Phase 3 — Scale: Multi-Platform & PostgreSQL

| Milestone | Status | Description |
|-----------|--------|-------------|
| 3.1 — Polymarket Adapter | Pending | Polymarket auth, CLOB/RTDS WebSocket, event normalization |
| 3.2 — PostgreSQL Migration | Pending | Schema migration, table partitioning, materialized views |
| 3.3 — Cross-Platform Correlation | Pending | Cross-platform topic graph, data retention policies |

### Phase 4 — Integration: Convex Sync & Webapp

| Milestone | Status | Description |
|-----------|--------|-------------|
| 4.1 — Sync Layer | Pending | PostgreSQL-to-Convex sync, event-driven alerts, scheduled aggregates |
| 4.2 — Webapp Updates | Pending | Dashboard views, anomaly feed, trending topics |

### Phase 5 — Intelligence: LLM Narrative Layer

| Milestone | Status | Description |
|-----------|--------|-------------|
| 5.1 — LLM Narrative Layer | Pending | Catalyst attribution, template-based control, blind evaluation |

## Prerequisites

- Python 3.11+
- [Poetry](https://python-poetry.org/)

## Setup

```bash
# Install dependencies
poetry install

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your Kalshi API key, private key path, and Anthropic API key

# Initialize the database
poetry run nexus db-init
```

## Usage

### Ingestion

```bash
# Show configuration
poetry run nexus info

# Run a single discovery cycle
poetry run nexus discover

# Start full ingestion (REST discovery + WebSocket streaming)
poetry run nexus run

# Start discovery-only polling (no WebSocket)
poetry run nexus poll

# Stream WebSocket events to console (debug)
poetry run nexus stream

# Check database statistics
poetry run nexus db-stats

# Run data integrity validation and Decision Gate check
poetry run nexus validate
```

### Anomaly Detection

```bash
# Run a single detection cycle (single-market + cluster correlation)
poetry run nexus detect

# Run standalone cluster correlation
poetry run nexus correlate

# List recent anomalies
poetry run nexus anomalies
poetry run nexus anomalies --anomaly-type cluster --since-hours 48

# Show anomaly signal quality statistics
poetry run nexus anomaly-stats

# Show Decision Gate signal analysis report
poetry run nexus signal-report --days 7
```

### Topic Clustering

```bash
# Run topic clustering on unassigned markets
poetry run nexus cluster
poetry run nexus cluster --mode batch

# List all topic clusters
poetry run nexus clusters --show-markets

# Show clustering quality statistics
poetry run nexus cluster-stats
```

## Testing

```bash
poetry run pytest tests/ -v
```

158 tests across 17 test modules covering store CRUD, adapters, ingestion, anomaly detection, clustering, and correlation.

## Project Structure

```
nexus/                  Python package
  core/                 Configuration, logging, shared types
  adapters/             Platform adapters (Kalshi, Polymarket)
  ingestion/            Discovery polling, event bus, WebSocket manager
  store/                Database abstraction (SQLite, PostgreSQL)
  correlation/          Anomaly detection, windowed stats, cluster correlation
  clustering/           LLM-powered topic clustering (Claude)
  sync/                 Convex sync layer (Phase 4)
  cli.py                Command-line interface
sql/                    Schema DDL and migrations
tests/                  Test suite (158 tests)
```

### Key Components

- **WindowComputer** — Sliding window statistics over the event store (price delta, volume, trade count)
- **AnomalyDetector** — Three detection rules: price change threshold, volume spike multiplier, Z-score breach
- **DetectionLoop** — Periodic runner for anomaly detection + cluster correlation
- **TopicClusterer** — LLM-based semantic clustering with batch and incremental modes
- **ClusterCorrelator** — Detects concurrent anomalies across markets in the same topic cluster
- **EventBus** — Async bounded queue with batch drain for high-throughput event ingestion

## Architecture

See `projectnexus_specdoc.md` for the full specification.
