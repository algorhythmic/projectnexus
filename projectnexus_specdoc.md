# NEXUS — Real-Time Prediction Market Intelligence Engine

> Project Specification & Implementation Plan
> Version 1.0 — February 2026

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Project Genesis & Rationale](#2-project-genesis--rationale)
3. [Objectives & Success Criteria](#3-objectives--success-criteria)
4. [Competitive Landscape Analysis](#4-competitive-landscape-analysis)
5. [Platform API Assessment](#5-platform-api-assessment)
6. [System Architecture](#6-system-architecture)
7. [Data Architecture & Migration Path](#7-data-architecture--migration-path)
8. [Implementation Phases](#8-implementation-phases)
9. [Repository & Project Structure](#9-repository--project-structure)
10. [Relationship to MarketFinder](#10-relationship-to-marketfinder)
11. [Risk Assessment & Mitigations](#11-risk-assessment--mitigations)
12. [Future Expansion Domains](#12-future-expansion-domains)
13. [Appendices](#13-appendices)

---

## 1. Executive Summary

Nexus is a real-time prediction market intelligence engine that ingests streaming data from prediction market platforms (initially Kalshi and Polymarket), detects anomalous price and volume movements, identifies correlated shifts across semantically related markets, and surfaces structured alerts for human decision-making.

The project originates from MarketFinder, an existing cross-platform arbitrage detection system built with React, Convex, and a Python/TypeScript ETL pipeline. While MarketFinder focuses narrowly on identifying price discrepancies between platforms for arbitrage, Nexus expands the scope to real-time market analytics: trending markets, volume surges, cross-market correlation, and structured intelligence about what is moving and why.

Nexus serves two concurrent objectives:

**Track 1 — Learning Build:** Validate technical hypotheses about real-time ingestion, cross-market correlation detection, and the signal-to-noise ratio of anomaly detection. Produce a portfolio artifact demonstrating systems design, streaming architecture, and data engineering proficiency.

**Track 2 — Income Path:** If hypotheses validate, either (a) use the system as a personal trading edge by detecting market movements before they surface in existing tools, or (b) productize the underserved capability gaps identified through competitive analysis — specifically the structured "why is this moving" intelligence layer that existing tools lack.

> **Key Architectural Decision:** Nexus uses PostgreSQL (preceded by SQLite for rapid prototyping) as its source of truth for event storage and analytical queries. MarketFinder's Convex backend becomes a thin presentation layer populated by a sync process from Postgres views. This separates the analytical workload from the webapp rendering layer, allowing each system to use the technology best suited to its role.

---

## 2. Project Genesis & Rationale

### 2.1 From MarketFinder to Nexus

MarketFinder consists of two repositories: `marketfinder-main` (a React + Convex webapp) and `marketfinder_ETL` (a data pipeline with both TypeScript scripts and a Python package). Both share a Convex deployment and an identical schema, with duplicated Convex functions across repos. A monorepo migration was planned to consolidate them.

During the planning process for the monorepo migration, the scope expanded. MarketFinder's arbitrage detection — while valuable — addresses a narrow use case in an increasingly crowded competitive landscape. The underlying capabilities (platform data extraction, LLM-powered semantic matching, cross-market analysis) have broader applicability when reframed around real-time market intelligence rather than just arbitrage.

This reframing led to Nexus: a system that asks not just "where are the price discrepancies?" but "what is the market paying attention to right now, and how is sentiment shifting?"

### 2.2 Why Not Just Extend MarketFinder?

Several factors argued for a new project rather than evolving MarketFinder:

- Nexus's core workload (streaming ingestion, windowed analytics, event-sourced storage) is fundamentally different from a webapp backend. Convex excels at reactive UI queries but is poorly suited to high-frequency writes and analytical aggregations.
- The technology stack diverges: Nexus is Python-first (data engineering, ML, time-series analysis), while MarketFinder is TypeScript/React. A monorepo containing both would be two disconnected projects sharing a build tool.
- Different deployment models: MarketFinder deploys to Vercel + Convex (serverless), Nexus deploys as a long-running process with a PostgreSQL instance (stateful server).
- Different development cadences: Nexus would be under active development while MarketFinder is relatively stable.

---

## 3. Objectives & Success Criteria

### 3.1 Hypotheses to Validate

> **Hypothesis A — Real-Time Cross-Market Correlation (Priority 1)**
>
> It is technically feasible to maintain persistent WebSocket connections to Kalshi and Polymarket, normalize their event streams into a unified format, and detect when semantically related markets move in concert — all on a single modest server, with acceptable latency and reliability.

> **Hypothesis B — Anomaly Detection Signal Quality (Priority 2)**
>
> Windowed anomaly detection over the normalized event stream produces a usable signal-to-noise ratio. Specifically: the system generates fewer than 50 alerts per day at default thresholds, and at least 60% of generated alerts correspond to verifiable real-world catalysts (news events, data releases, policy announcements).

> **Hypothesis C — LLM Narrative vs. Structured Templates (Priority 3)**
>
> When a cluster anomaly fires, passing the anomaly context through an LLM to correlate with recent news produces meaningfully better structured alerts than a template-based approach. "Meaningfully better" defined as: a blind evaluator prefers the LLM-generated alert 70%+ of the time.

### 3.2 Track 1 Success Criteria (Learning Build)

1. Maintain stable WebSocket connections to at least one platform for 72+ continuous hours without manual intervention.
2. Normalize and store 100,000+ events in the event store with correct timestamps, deduplication, and queryable time-windowed aggregations.
3. Detect at least 5 genuine correlated market movements across a one-week observation period, validated against external news sources.
4. Document all failure modes encountered: connection drops, rate limit violations, event ordering issues, backpressure scenarios.
5. Produce a written technical analysis of the signal-to-noise ratio at various anomaly detection thresholds.

### 3.3 Track 2 Success Criteria (Income Path)

These criteria are contingent on Track 1 validation:

1. **Path 2A (Personal Trading):** Identify at least 3 tradeable opportunities per month that the system surfaced before they were visible in competing tools (Oddpool, Adjacent News).
2. **Path 2B (Product):** If the structured intelligence layer proves valuable, define the minimum viable API surface, build a prototype with 10 beta users, and validate willingness to pay.

---

## 4. Competitive Landscape Analysis

The prediction market tooling ecosystem has grown significantly, with 170+ third-party tools in the Polymarket ecosystem alone. Understanding the competitive landscape is essential for identifying where genuine value gaps exist versus where existing solutions are adequate.

### 4.1 Direct Competitors

| Tool | Category | Key Capabilities | Gap / Limitation |
|------|----------|-----------------|------------------|
| **Oddpool** | Aggregator / Terminal | Cross-venue odds, arbitrage alerts, whale tracking, historical data | Focuses on *what* is moving, not *why*; no narrative synthesis or catalyst attribution |
| **Alphascope** | AI Signals | Real-time signals, probability shift detection, news impact analysis | Primarily Polymarket-focused; limited cross-platform correlation |
| **Adjacent News** | Narrative / News | Generates news stories from odds shifts; semantic search; 40K+ markets; API | News article format, not structured machine-readable alerts; reactive, not predictive |
| **Verso** | Terminal | Bloomberg-style interface; real-time data and news for institutional traders | Presentation layer over existing data; no proprietary analytics engine |
| **Forcazt** | AI Analytics | High-alpha market discovery, arbitrage, data-driven edge | Aggregator with AI overlay; limited real-time correlation |
| **Predly** | Alert System | Pricing error detection on Polymarket and Kalshi; 89% alert accuracy claim | Narrow focus on mispricing; no narrative or cluster analysis |
| **Dome / PolyRouter** | Developer API | Unified cross-platform data APIs and SDKs | Data normalization only; no analytics or intelligence layer |

### 4.2 Identified Value Gaps

Three underserved areas emerge from the competitive analysis:

**1. The "Why Is This Moving?" Layer:** Most tools report what is moving (price changes, volume spikes). Few explain why with structured, machine-readable catalyst attribution. Adjacent News generates human-readable articles, but there is no tool producing structured alert objects like: `{clusterTopic: "Fed Policy", marketsMoved: 8, direction: "bearish", timeWindow: "20min", possibleCatalyst: "FOMC minutes release", confidence: 0.85}`.

**2. Cross-Domain Signal Bridge:** Every existing tool is built for prediction market traders. Prediction market signals have untapped value for audiences who don't trade these markets: journalists (early story detection), policy analysts (sentiment shifts), hedge fund researchers (alternative data signals), corporate strategists (risk indicators).

**3. Clustering-as-a-Service:** Dome and PolyRouter normalize data across platforms. No tool offers the semantic clustering and correlation detection as a consumable API. Developers building prediction market tools could benefit from a service that answers: "given this market moved, what other markets are semantically related and also moving?"

---

## 5. Platform API Assessment

### 5.1 Kalshi API

Kalshi offers REST, WebSocket, and FIX 4.4 protocol interfaces as a CFTC-regulated exchange.

| Aspect | Details |
|--------|---------|
| WebSocket URL | `wss://trading-api.kalshi.com/trade-api/ws/v2` |
| Authentication | RSA-PSS signed requests (already implemented in `kalshi-auth.ts`) |
| Channels | Orderbook updates, trade executions, market status changes |
| Rate Limits (Basic) | 20 reads/sec, 10 writes/sec — free with signup |
| Rate Limits (Advanced) | 30/30 — requires application form |
| Rate Limits (Premier/Prime) | 100-400/sec — requires 3.75-7.5% of monthly exchange volume |
| API Cost | Free for all tiers; tiers only throttle throughput |
| Market Coverage | ~3,500 markets; defined trading hours (not 24/7) |
| Demo Environment | Full sandbox at `demo-api.kalshi.com` |

> **Recommendation: Start with Kalshi.** Existing RSA auth infrastructure (`kalshi-auth.ts`) enables rapid implementation. The Basic tier's 20 reads/sec is sufficient for a single-user analytics system. The demo environment allows development without risking production rate limits. Polymarket can be added as a second adapter once the pipeline is proven.

### 5.2 Polymarket API

Polymarket provides two separate WebSocket services plus REST endpoints, operating on the Polygon blockchain.

| Aspect | Details |
|--------|---------|
| CLOB WebSocket | `wss://ws-subscriptions-clob.polymarket.com` — Level 2 orderbook, trades |
| RTDS WebSocket | `wss://ws-live-data.polymarket.com` — activity feeds, crypto prices, comments |
| Authentication | EIP-712 wallet signatures (L1) + HMAC-SHA256 API credentials (L2) |
| Rate Limits (Free) | ~100 requests/min; `/books` endpoint: 300 per 10 seconds |
| Rate Limits (Premium) | $99/month for WebSocket feeds and deeper historical data |
| Throttling | Cloudflare-based; requests queued, not rejected |
| Market Coverage | ~1,000+ active markets; 24/7 operation (crypto-based) |
| Client Libraries | Official Python client (`py-clob-client`); TypeScript RTDS client |

### 5.3 Key API Limitation

Neither platform offers a firehose-style webhook that pushes every new market creation and every price change globally. Both require subscribing to specific market tickers or asset IDs. This necessitates a hybrid architecture:

- **Periodic REST polling** (30-60 second intervals) to discover new markets and maintain the market registry.
- **WebSocket subscriptions** for real-time price and volume updates on tracked markets.
- The market discovery polling is how "hot new markets" are detected — by comparing the current market list against the known registry and flagging new entries with rapid initial volume.

---

## 6. System Architecture

### 6.1 Architecture Overview

Nexus follows a layered pipeline architecture with four core responsibilities: Discover, Subscribe, Normalize & Store, and Correlate. Each layer has a clean interface, enabling independent testing and technology substitution.

```
┌─────────────────────────────────────────────────────┐
│                    Nexus Core                        │
│                                                      │
│  ┌───────────┐  ┌────────────┐  ┌────────────────┐  │
│  │  Kalshi   │  │ Polymarket │  │    Future      │  │
│  │  Adapter  │  │  Adapter   │  │    Adapters    │  │
│  └─────┬─────┘  └─────┬──────┘  └───────┬────────┘  │
│        │               │                 │           │
│        ▼               ▼                 ▼           │
│  ┌───────────────────────────────────────────────┐   │
│  │          Event Bus (normalized events)         │   │
│  │     {marketId, platform, type, value, ts}      │   │
│  └──────────┬────────────────────┬───────────────┘   │
│             │                    │                    │
│    ┌────────▼───────┐   ┌───────▼──────────┐         │
│    │  Event Store   │   │  Correlation     │         │
│    │  (append-only) │   │  Engine          │         │
│    │                │   │  - topic graph   │         │
│    │  SQLite (P1)   │   │  - windowed      │         │
│    │  Postgres (P2) │   │    anomaly det.  │         │
│    │                │   │  - cluster       │         │
│    │                │   │    detection     │         │
│    └────────────────┘   └───────┬──────────┘         │
│                                 │                    │
│                        ┌────────▼──────────┐         │
│                        │  Alert Emitter    │         │
│                        │  (structured      │         │
│                        │   anomaly objs)   │         │
│                        └────────┬──────────┘         │
│                                 │                    │
│                        ┌────────▼──────────┐         │
│                        │  Sync Layer       │         │
│                        │  (Postgres views  │         │
│                        │   → Convex)       │         │
│                        └───────────────────┘         │
└─────────────────────────────────────────────────────┘
```

### 6.2 Component Descriptions

**Platform Adapters:** Each prediction market platform is accessed through an adapter implementing a common interface. The adapter contract defines two methods: `discover()` returns normalized market metadata from REST polling, and `connect()` returns a normalized event stream from WebSocket subscriptions. This abstraction means the correlation engine is platform-agnostic — adding a new platform is additive, not a rewrite.

**Event Bus:** An in-process async event bus routes normalized events from adapters to consumers (event store and correlation engine). For the MVP, this is a simple Python asyncio queue or EventEmitter equivalent. If the system later needs to separate ingestion and correlation into different processes, this is the seam where a message broker (Redis Streams, etc.) would be introduced.

**Event Store:** An append-only log of every normalized event, queryable for windowed aggregations. SQLite in Phase 1 (embedded, zero configuration), PostgreSQL in Phase 2 (standalone, concurrent access, partitioning). The schema is identical between both — migration is a connection string change plus minor syntax adjustments.

**Correlation Engine:** Consults the topic graph (semantic clusters of related markets) and runs windowed anomaly detection. When a market triggers an anomaly, the engine checks whether other markets in the same topic cluster are also anomalous within the time window. Cluster anomalies are emitted as structured alert objects.

**Topic Graph:** A semantic mapping of markets into topic clusters, built using the LLM matching infrastructure ported from MarketFinder. Runs as a background job when new markets are discovered. The graph is persisted in the event store database and consulted in real-time by the correlation engine.

**Alert Emitter:** Structured anomaly objects output by the correlation engine. In Phase 1, these are logged to stdout/file for analysis. In Phase 3, they are synced to Convex for the MarketFinder webapp to display.

**Sync Layer (Phase 3):** A bridge process that reads PostgreSQL views (precomputed analytical summaries) and writes lean, purpose-built records into Convex tables. Event-driven for high-priority alerts (immediate push to Convex), scheduled for aggregate state (market summaries, trending topics). The Convex tables become a narrow presentation layer — the webapp reads from Convex, not from Postgres.

### 6.3 Data Flow

The end-to-end data flow is unidirectional:

1. **Platform APIs** (Kalshi, Polymarket) emit raw market data via WebSocket streams and REST endpoints.
2. **Platform Adapters** normalize raw data into unified event objects: `{marketId, platform, eventType, value, timestamp}`.
3. **The Event Bus** routes normalized events to the Event Store (durable persistence) and the Correlation Engine (real-time analysis).
4. **The Event Store** persists every event for historical queries and windowed aggregations.
5. **The Correlation Engine** detects anomalies (individual market movements) and cluster anomalies (correlated movements across topic-related markets).
6. **The Alert Emitter** produces structured alert objects for consumption.
7. **The Sync Layer** (Phase 3) reads PostgreSQL analytical views and writes precomputed summaries into Convex tables.
8. **The MarketFinder webapp** reads from Convex tables and renders the dashboard UI with real-time reactivity.

> **Design Principle: Separation of Concerns.** Each component owns one responsibility. The adapters don't know about anomaly detection. The correlation engine doesn't know about Convex. The sync layer doesn't know about WebSockets. This enables independent testing, clear failure boundaries, and technology substitution at any layer.

---

## 7. Data Architecture & Migration Path

### 7.1 Three-Phase Storage Migration

| Phase | Storage | Purpose | When |
|-------|---------|---------|------|
| Phase 1 | SQLite (embedded) | Rapid prototyping; validate Hypothesis A with zero infrastructure overhead | Immediate |
| Phase 2 | PostgreSQL | Durable analytical store; concurrent access; partitioning; materialized views | After Hypothesis A validates |
| Phase 3 | PostgreSQL + Convex | Postgres as source of truth; Convex as presentation layer for webapp | When webapp integration begins |

### 7.2 Core Event Store Schema

The following schema is designed to work identically in SQLite and PostgreSQL.

#### `markets` table

Registry of all known markets across platforms.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PRIMARY KEY | Auto-increment |
| `platform` | TEXT NOT NULL | `'kalshi'` or `'polymarket'` |
| `external_id` | TEXT NOT NULL | Platform-specific identifier |
| `title` | TEXT NOT NULL | Market title |
| `description` | TEXT | Market description |
| `category` | TEXT | Standardized category |
| `is_active` | BOOLEAN | Current status |
| `first_seen_at` | INTEGER NOT NULL | Unix ms timestamp |
| `last_updated_at` | INTEGER NOT NULL | Unix ms timestamp |

- Unique constraint on `(platform, external_id)` for upsert operations.
- Indexes on `platform`, `category`, `is_active`.

#### `events` table

Append-only log of every normalized price/volume event.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PRIMARY KEY | Auto-increment |
| `market_id` | INTEGER NOT NULL | FK → `markets.id` |
| `event_type` | TEXT NOT NULL | `'price_change'`, `'volume_update'`, `'status_change'`, `'new_market'` |
| `old_value` | REAL | Nullable; previous value |
| `new_value` | REAL NOT NULL | Current value |
| `metadata` | TEXT | JSON for additional context |
| `timestamp` | INTEGER NOT NULL | Unix ms timestamp |

- Indexes on `market_id`, `event_type`, `timestamp`.
- In PostgreSQL Phase 2: range-partitioned by `timestamp` for efficient retention and querying.

#### `topic_clusters` table

Semantic groupings of related markets.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PRIMARY KEY | Auto-increment |
| `name` | TEXT NOT NULL | Cluster name (e.g., "Fed Policy") |
| `description` | TEXT | Description of the topic |
| `created_at` | INTEGER NOT NULL | Unix ms timestamp |
| `updated_at` | INTEGER NOT NULL | Unix ms timestamp |

#### `market_cluster_memberships` table

Junction table mapping markets to topic clusters.

| Column | Type | Notes |
|--------|------|-------|
| `market_id` | INTEGER NOT NULL | FK → `markets.id` |
| `cluster_id` | INTEGER NOT NULL | FK → `topic_clusters.id` |
| `confidence` | REAL NOT NULL | 0–1 from LLM matching |
| `assigned_at` | INTEGER NOT NULL | Unix ms timestamp |

#### `anomalies` table

Detected anomaly events.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PRIMARY KEY | Auto-increment |
| `anomaly_type` | TEXT NOT NULL | `'single_market'` or `'cluster'` |
| `severity` | REAL NOT NULL | Computed severity score |
| `topic_cluster_id` | INTEGER | FK → `topic_clusters.id` (nullable for single-market) |
| `market_count` | INTEGER NOT NULL | Number of affected markets |
| `window_start` | INTEGER NOT NULL | Unix ms timestamp |
| `detected_at` | INTEGER NOT NULL | Unix ms timestamp |
| `summary` | TEXT | Human-readable summary |
| `status` | TEXT NOT NULL | `'active'`, `'expired'`, `'acknowledged'` |
| `metadata` | TEXT | JSON for additional context |

#### `anomaly_markets` table

Junction table linking anomalies to specific markets involved.

| Column | Type | Notes |
|--------|------|-------|
| `anomaly_id` | INTEGER NOT NULL | FK → `anomalies.id` |
| `market_id` | INTEGER NOT NULL | FK → `markets.id` |
| `price_delta` | REAL | Price change magnitude |
| `volume_ratio` | REAL | Volume spike ratio |

### 7.3 PostgreSQL Analytical Views (Phase 2-3)

PostgreSQL views serve as the API contract between Nexus and the sync layer. Each view encapsulates analytical complexity so the sync process is trivially simple — it reads view output and writes to Convex.

**`v_current_market_state`:** Materialized view of the latest price and volume for each active market, derived from the most recent event per market. Refreshed on a short schedule or triggered by the ingestion process.

**`v_active_anomalies`:** Join of anomalies, anomaly_markets, and markets tables filtered to `status = 'active'`. Includes the affected markets as a JSON aggregate. This is what the webapp's anomaly panel reads.

**`v_trending_topics`:** Topic clusters ranked by the number of anomalous events in the last N hours. Powers the "what is the market paying attention to" display.

**`v_market_summaries`:** Per-market 24-hour statistics: price high/low/change, volume total, anomaly count. Powers individual market detail views.

### 7.4 Convex Target Schema (Phase 3)

Convex tables are narrow and purpose-built for UI rendering. They do not replicate the full analytical data — only precomputed summaries:

| Convex Table | Source View | Sync Frequency | Purpose |
|-------------|-------------|----------------|---------|
| `markets` | `v_current_market_state` | Every 30 seconds | Current prices for market list display |
| `activeAnomalies` | `v_active_anomalies` | Event-driven (immediate) | Real-time anomaly alert panel |
| `trendingTopics` | `v_trending_topics` | Every 5 minutes | Dashboard trending topics widget |
| `marketSummaries` | `v_market_summaries` | Every 2 minutes | Individual market detail pages |

---

## 8. Implementation Phases

Each phase has clear deliverables, success criteria, and a decision gate before proceeding to the next.

### 8.1 Phase 1: Foundation — Single-Platform Ingestion (Weeks 1–3)

**Objective:** Validate Hypothesis A. Establish a working real-time ingestion pipeline from Kalshi into a SQLite event store.

#### Milestone 1.1 — Project Scaffolding (Week 1)

- Initialize the `nexus` repository with Python project structure (`pyproject.toml`, Poetry, src layout).
- Define the adapter interface: `BaseAdapter` abstract class with `discover()` and `connect()` methods.
- Create the SQLite event store schema (`markets`, `events` tables).
- Port `kalshi-auth.ts` to Python (or wrap via subprocess if expedient for MVP).
- Implement the market discovery polling loop (REST-based market enumeration).

#### Milestone 1.2 — Kalshi WebSocket Adapter (Week 2)

- Implement WebSocket connection with RSA-PSS authentication.
- Handle connection lifecycle: initial connect, reconnection on drop, ping/pong keepalive.
- Subscribe to orderbook and trade channels for discovered markets.
- Normalize Kalshi events (yes/no prices in cents, orderbook snapshots) into unified event format.
- Write normalized events to SQLite event store.
- Implement backpressure handling: what happens when events arrive faster than SQLite can write?

#### Milestone 1.3 — Stability Testing (Week 3)

- Run the ingestion pipeline continuously for 72+ hours.
- Log and categorize all failure modes: disconnections, auth token expiry, rate limit hits, data gaps.
- Implement monitoring: events/second throughput, connection uptime, error rates.
- Validate data integrity: query the event store for gaps, duplicates, timestamp ordering.

> **Phase 1 Decision Gate:** Proceed to Phase 2 if: the pipeline runs stably for 72+ hours, the event store contains 100K+ valid events, and failure modes are documented with mitigations implemented. If the pipeline is fundamentally unstable (e.g., Kalshi aggressively disconnects non-trading WebSocket clients), reassess the architecture before continuing.

### 8.2 Phase 2: Analytics — Anomaly Detection (Weeks 4–6)

**Objective:** Validate Hypothesis B. Build the anomaly detection engine and measure signal quality.

#### Milestone 2.1 — Windowed Anomaly Detection (Week 4)

- Implement sliding window computations over the event store: configurable windows (5min, 15min, 1hr, 24hr).
- Define anomaly detection rules: percentage price change threshold, volume spike multiplier, Z-score against historical baseline.
- Create the `anomalies` and `anomaly_markets` tables.
- Build a CLI tool for querying anomalies: filter by time range, severity, market, cluster.

#### Milestone 2.2 — Topic Graph Construction (Week 5)

- Port MarketFinder's LLM semantic matching logic to Python.
- Build the `topic_clusters` and `market_cluster_memberships` tables.
- Run initial clustering: group all markets in the registry into topic clusters using LLM matching.
- Implement incremental clustering: when new markets are discovered, assign them to existing clusters or create new ones.
- Validate cluster quality: manual review of cluster assignments for coherence.

#### Milestone 2.3 — Correlation Detection & Signal Analysis (Week 6)

- Implement cluster anomaly detection: when an individual anomaly fires, check other markets in the same topic cluster for concurrent anomalies.
- Emit structured cluster anomaly alerts with: topic, affected markets, direction, magnitude, time window.
- Run for one full week, collecting all alerts.
- Manually validate alerts against external news sources (news APIs, Twitter, official announcements).
- Calculate signal-to-noise ratio: what percentage of alerts correspond to real catalysts?
- Tune thresholds based on results. Document findings.

> **Phase 2 Decision Gate:** Proceed to Phase 3 if: the system generates a manageable alert volume (< 50/day at tuned thresholds), and > 60% of cluster anomaly alerts correspond to verifiable real-world catalysts. If signal quality is poor, iterate on detection algorithms before adding complexity.

### 8.3 Phase 3: Scale — Multi-Platform & PostgreSQL (Weeks 7–9)

**Objective:** Add Polymarket as a second data source. Migrate from SQLite to PostgreSQL. Enable richer analytics.

#### Milestone 3.1 — Polymarket Adapter (Week 7)

- Implement Polymarket authentication (EIP-712 wallet signatures, HMAC API credentials).
- Build the Polymarket adapter implementing the same `BaseAdapter` interface.
- Handle dual WebSocket services: CLOB for orderbook data, RTDS for activity feeds.
- Normalize Polymarket events (token-based bid/ask spreads) into the same unified format.
- Run both adapters concurrently; verify events from both platforms interleave correctly in the event store.

#### Milestone 3.2 — PostgreSQL Migration (Week 8)

- Set up PostgreSQL instance (local Docker for dev, managed service for production).
- Migrate the SQLite schema to PostgreSQL. Adjust syntax where needed (e.g., `AUTOINCREMENT` → `SERIAL`, JSON handling).
- Implement table partitioning on the `events` table by timestamp (monthly or weekly partitions).
- Create materialized views: `v_current_market_state`, `v_active_anomalies`, `v_trending_topics`, `v_market_summaries`.
- Backfill PostgreSQL with historical data from the SQLite event store.
- Switch the ingestion pipeline to write to PostgreSQL. Verify performance under load.

#### Milestone 3.3 — Cross-Platform Correlation (Week 9)

- Extend the topic graph to include cross-platform market relationships (Kalshi market X is semantically equivalent to Polymarket market Y).
- Test cross-platform cluster anomaly detection: do correlated movements between platforms produce higher-quality signals?
- Implement data retention policies: partition pruning for events older than configurable threshold.

### 8.4 Phase 4: Integration — Convex Sync & Webapp (Weeks 10–12)

**Objective:** Connect Nexus to the MarketFinder webapp via the sync layer. Build dashboard views for the new data.

#### Milestone 4.1 — Sync Layer (Week 10)

- Implement the PostgreSQL-to-Convex sync process.
- Event-driven sync for anomaly alerts: when the correlation engine emits an alert, immediately push to Convex.
- Scheduled sync for aggregate data: market state every 30s, summaries every 2min, trending topics every 5min.
- Define and implement Convex target tables: `markets`, `activeAnomalies`, `trendingTopics`, `marketSummaries`.
- Handle idempotency: sync operations must be safe to retry without creating duplicates.

#### Milestone 4.2 — Webapp Updates (Weeks 11–12)

- Update MarketFinder's Convex queries to read from the new sync-populated tables.
- Build new dashboard views: real-time anomaly feed, trending topics panel, market detail with event timeline.
- Replace mock data in existing views (ArbitrageView, MarketsView) with live Convex data.
- Ensure Convex's reactive subscriptions provide real-time UI updates when the sync layer pushes new data.

### 8.5 Phase 5: Intelligence — LLM Narrative Layer (Weeks 13–14)

**Objective:** Validate Hypothesis C. Add LLM-powered catalyst attribution and narrative generation.

- Implement LLM-powered alert enrichment: when a cluster anomaly fires, pass the context to an LLM with a news API feed to attribute a likely catalyst.
- Implement template-based alert generation as a control condition.
- Run both systems in parallel for two weeks, producing paired outputs.
- Conduct blind evaluation: does the LLM version provide meaningfully better context?
- Based on results, decide whether the LLM layer justifies its cost and latency.

---

## 9. Repository & Project Structure

### 9.1 Nexus Repository

Nexus is a standalone Python-first repository, separate from MarketFinder.

```
nexus/
├── nexus/                          # Main Python package
│   ├── core/                       # Configuration, logging, shared types, constants
│   ├── adapters/                   # Platform adapter implementations
│   │   ├── base.py                 # Abstract BaseAdapter interface
│   │   ├── kalshi.py               # Kalshi REST + WebSocket adapter
│   │   └── polymarket.py           # Polymarket CLOB + RTDS adapter
│   ├── ingestion/                  # Event normalization, bus, orchestration
│   ├── store/                      # Database abstraction (SQLite / PostgreSQL)
│   │   ├── base.py                 # Abstract store interface
│   │   ├── sqlite.py               # SQLite implementation
│   │   └── postgres.py             # PostgreSQL implementation
│   ├── correlation/                # Anomaly detection, topic graph, cluster engine
│   ├── sync/                       # PostgreSQL-to-Convex sync layer
│   └── cli.py                      # Command-line entry point
├── sql/
│   ├── schema.sql                  # Event store schema
│   ├── migrations/                 # Schema migration scripts
│   └── views/                      # Analytical view definitions
├── tests/                          # Unit and integration tests
├── docs/                           # Technical documentation
├── pyproject.toml                  # Poetry configuration
├── docker-compose.yml              # PostgreSQL + Nexus (Phase 2+)
└── README.md
```

### 9.2 MarketFinder Repository (Tidied)

The existing `marketfinder-main` repository stays as the React + Convex webapp. Tidying tasks (not a full restructuring):

- Fix schema issues: add missing indexes, resolve field name mismatches (`platformId` vs `platform`, `status` vs `isActive`, `totalVolume` vs `volume`).
- Remove mock data from components (ArbitrageView, DashboardOverview sample data initialization).
- Clean out unused Convex functions that duplicate ETL repo logic.
- Update Convex schema to include the sync target tables (`activeAnomalies`, `trendingTopics`, `marketSummaries`).
- Remove duplicate documentation, stale configuration files.

### 9.3 ETL Repository (Deprecated)

The `marketfinder_ETL` repository is archived. Its assets are distributed as follows:

| ETL Asset | Destination | Notes |
|-----------|-------------|-------|
| `src/marketfinder_etl/extractors/` | `nexus/nexus/adapters/` | Ported and extended with WebSocket support |
| `src/marketfinder_etl/engines/` | `nexus/nexus/correlation/` | Filtering, bucketing, ML scoring logic reused |
| `src/marketfinder_etl/core/` | `nexus/nexus/core/` | Config and logging patterns reused |
| `scripts/production/*.ts` | Archived reference | TypeScript scripts superseded by Python adapters |
| `convex/` | Remains in `marketfinder-main` only | No longer duplicated |
| `dags/` | `nexus/dags/` (future) | Airflow patterns available if orchestration is needed |
| `docs/` | `nexus/docs/` (selectively) | Relevant docs carried forward; rest archived |
| `kalshi-auth.ts` | Ported to Python in `nexus/nexus/adapters/` | Or wrapped via subprocess for MVP |

---

## 10. Relationship to MarketFinder

### 10.1 Integration Model

Nexus and MarketFinder are separate systems connected by a well-defined data interface. They share no runtime dependencies, no database, and no deployment pipeline.

| Aspect | Nexus | MarketFinder |
|--------|-------|-------------|
| Primary Language | Python | TypeScript / React |
| Database | SQLite → PostgreSQL | Convex |
| Deployment | Long-running process + VPS | Vercel (static) + Convex (managed) |
| Runtime Model | Persistent (WebSocket connections) | Serverless (request/response) |
| Data Relationship | Source of truth (event store) | Presentation layer (sync target) |
| Development Cadence | Active development | Maintenance + sync integration |

### 10.2 Shared Code

Minimal shared code exists between the two projects:

- Market data type definitions (market shape, event types) — defined in Nexus, consumed by the sync layer to write to Convex.
- Platform API constants (URLs, authentication parameters) — duplicated is acceptable given the small surface area.
- The `kalshi-auth` RSA signing logic — exists in TypeScript in MarketFinder and will be ported to Python in Nexus.

This level of duplication is intentional and preferable to coupling the two projects through shared packages. The sync layer is the only integration point, and it has a well-defined contract (PostgreSQL views in, Convex mutations out).

### 10.3 The Monorepo Migration Is No Longer Required

The original monorepo migration plan was motivated by Convex schema drift between the two repos sharing a deployment. With this architecture:

- The ETL repo is deprecated and absorbed into Nexus.
- MarketFinder keeps its own Convex schema as the sole owner.
- Nexus has its own database (SQLite/PostgreSQL) with no Convex dependency in its core.
- The schema drift problem is eliminated by eliminating the shared deployment, not by consolidating into a monorepo.

---

## 11. Risk Assessment & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Kalshi disconnects non-trading WebSocket clients aggressively | Medium | High — blocks Hypothesis A | Test early in Phase 1. Fallback: high-frequency REST polling (5-10s intervals) within rate limits. The adapter interface abstracts this. |
| Anomaly detection produces too much noise | Medium | Medium — blocks Hypothesis B | Iterative threshold tuning in Phase 2. Multiple detection algorithms (Z-score, percentage change, volume-weighted). Configurable sensitivity. |
| LLM costs exceed value for narrative generation | Low-Medium | Low — affects Hypothesis C only | Phase 5 is explicitly a controlled experiment. Template-based alerts work as fallback. LLM layer is additive, not foundational. |
| SQLite write throughput insufficient for event volume | Low | Medium — data loss during high activity | Batch writes (buffering events and writing in transactions). WAL mode for concurrent reads/writes. Early migration to PostgreSQL if needed. |
| Platform API changes or deprecation | Low | High — breaks ingestion | Adapter interface isolates platform-specific code. API version pinning. Monitoring for connection failures as early warning. |
| Scope creep into building a full product before validating hypotheses | High | High — wasted effort | Strict phase gates. No Phase 3 work before Phase 1 decision gate. Track 2 decisions deferred until Track 1 results are in hand. |

---

## 12. Future Expansion Domains

The core pattern Nexus implements — real-time signal ingestion, semantic clustering, windowed anomaly detection, and structured alerting — is domain-agnostic. If the architecture validates in the prediction market domain, these adjacent domains share the same technical requirements:

**Crypto / DeFi Analytics:** Token launches, liquidity pool movements, governance proposals, whale wallet tracking. Replace "markets" with "tokens/pools" and the pipeline transfers directly. Polymarket's blockchain foundation makes this a natural adjacent domain.

**Regulatory & Policy Intelligence:** Prediction markets alongside SEC EDGAR filings, Federal Register publications, congressional activity, lobbying disclosures. When prediction markets shift before public filings, that signal has value for legal teams, lobbyists, and institutional investors.

**Sports Betting Market Intelligence:** Line movements across sportsbooks, sharp money detection, injury news correlation with odds shifts. Architecturally identical to prediction market analytics but applied to a much larger and more liquid market.

**Media & Narrative Tracking:** Monitor which topics generate new prediction markets and attract volume. Cross-reference with social media velocity and news coverage. Prediction markets as a leading indicator for news cycle dominance.

**Venture / Startup Signal Detection:** Markets related to tech companies, product launches, IPOs alongside hiring data, patent filings, and app store rankings. Early signals of company trajectory before earnings.

These domains are noted for future consideration and are explicitly out of scope for the current implementation plan. Each would require its own adapter implementation but could share the correlation engine, anomaly detection, and alerting infrastructure.

---

## 13. Appendices

### 13.1 Technology Stack Summary

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| Language (Nexus core) | Python 3.11+ | Strongest ecosystem for data engineering, ML, time-series. AsyncIO for concurrent WebSocket handling. |
| Language (MarketFinder) | TypeScript / React | Existing webapp; no change needed. |
| Event Store (Phase 1) | SQLite + `aiosqlite` | Zero infrastructure; embedded; sufficient for hypothesis validation. |
| Event Store (Phase 2+) | PostgreSQL 16+ | Partitioning, materialized views, concurrent access, rich analytical SQL. |
| Optional: Time-series ext. | TimescaleDB | Hypertables, continuous aggregates, retention policies. Evaluated in Phase 2. |
| Webapp Backend | Convex | Existing MarketFinder backend; reactive subscriptions for UI. |
| WebSocket Client | `websockets` (Python) | Standard async WebSocket library. Production-ready. |
| HTTP Client | `httpx` | Async HTTP for REST polling. Connection pooling. |
| LLM Integration | OpenAI / Anthropic / Google AI SDKs | Existing MarketFinder integrations ported to Python. |
| Dependency Management | Poetry | Lock files, virtual environments, reproducible builds. |
| Containerization | Docker + Docker Compose | PostgreSQL + Nexus process in Phase 2+. |
| Task Runner / CLI | Click or Typer | CLI for starting ingestion, running analytics, querying anomalies. |

### 13.2 Glossary

| Term | Definition |
|------|-----------|
| **Adapter** | A platform-specific module implementing the `BaseAdapter` interface for data extraction. |
| **Anomaly** | A statistically significant price or volume movement on a single market within a time window. |
| **Cluster Anomaly** | Multiple correlated anomalies across markets in the same semantic topic cluster. |
| **Event Store** | The append-only database of normalized market events (prices, volumes, status changes). |
| **Topic Cluster** | A group of semantically related markets identified by LLM matching (e.g., all Fed-related markets). |
| **Topic Graph** | The persistent data structure mapping markets to topic clusters and clusters to each other. |
| **Sync Layer** | The bridge process that reads PostgreSQL views and writes to Convex tables. |
| **Presentation Layer** | Convex tables optimized for UI rendering, populated by the sync layer. |
| **Source of Truth** | PostgreSQL — the authoritative store for all Nexus data. |

### 13.3 References

- Kalshi API Documentation: https://docs.kalshi.com
- Polymarket Documentation: https://docs.polymarket.com
- Polymarket CLOB WebSocket: `wss://ws-subscriptions-clob.polymarket.com`
- Polymarket RTDS: `wss://ws-live-data.polymarket.com`
- Awesome Prediction Market Tools: https://github.com/aarora4/Awesome-Prediction-Market-Tools
- Adjacent News API: https://docs.adj.news
- Oddpool: https://www.oddpool.com
- MarketFinder Monorepo Migration Plan: `MONOREPO_MIGRATION_PLAN.md` (superseded by this document)
