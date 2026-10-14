# Nexus

A prediction-market monitoring service that flags unusual price and volume moves and displays them in a React dashboard.

A raw price feed does not explain which moves matter. Nexus combines streaming ingestion, statistical anomaly detection, related-market clustering and optional Claude-written explanations. Its dashboard reads cached API responses, reducing repeated database queries per viewer.

**Proof:** 449 test functions in 33 modules ([tests](tests/)) · recorded daily database writes reduced from ~487K to ~50K by buffering price ticks in memory ([migration results](docs/event-stream-migration.md)). The test figure is a source count; the write figures are a historical deployment result.

[Dashboard](https://marketfinder.daviddunn.dev/) · [Architecture](#architecture)

## Quick start

Needs Python 3.11+ and [Poetry](https://python-poetry.org/). Run the mocked suite without API keys:

```bash
git clone https://github.com/algorhythmic/projectnexus.git
cd projectnexus
poetry install
poetry run pytest tests/  # PostgreSQL tests skip without TEST_POSTGRES_DSN
```

Live ingestion needs Kalshi credentials; Claude features require an Anthropic API key. See [Setup](#setup). The default environment is Kalshi demo with SQLite.

## Status and limits

Ingestion, detection, the REST API, dashboard and optional alert explanations are implemented. Formal signal-quality and narrative-preference evaluations remain open. The dashboard and API endpoint returned HTTP 200 on October 14, 2026; data freshness and ongoing ingestion were not verified. The test suite was not re-run for this update. The historical 161M-comparison redesign is not a current pre-filter or measured billing saving. [Validation details](#validation-and-deployment-notes).

---

## Detailed documentation

Nexus ingests streaming data from prediction market platforms (Kalshi, Polymarket), detects anomalous price and volume movements, identifies correlated shifts across semantically related markets, and surfaces structured alerts for human decision-making.

## Project Status

Statuses below were reconciled against the source tree, `CLAUDE.md` and `docs/` on 2026-10-14. "Done" means the code and tests are in the repository; operational results are called out separately.

### Phase 1 — Foundation: Single-Platform Ingestion

| Milestone | Status | Description |
|-----------|--------|-------------|
| 1.1 — Project Scaffolding | Done | Kalshi REST adapter with RSA-PSS auth, SQLite event store, market discovery loop, CLI |
| 1.2 — Kalshi WebSocket Adapter | Done | WebSocket streaming with auto-reconnect, event bus with batch drain, ingestion manager |
| 1.3 — Stability Testing | Done | Data integrity validation, gap/duplicate/ordering checks, Decision Gate CLI |

**Decision Gate: PASSED (recorded)** — 72h+ stable ingestion, 100K+ events, failure modes documented. The raw stability logs are not in this repository.

### Phase 2 — Analytics: Anomaly Detection

| Milestone | Status | Description |
|-----------|--------|-------------|
| 2.1 — Windowed Anomaly Detection | Done | Sliding windows (5/15/60/1440 min), three detection rules (price threshold, volume spike, Z-score), anomaly tables and CRUD |
| 2.2 — Topic Graph Construction | Done | LLM-powered semantic clustering via Claude, batch and incremental modes, cluster management CLI |
| 2.3 — Correlation Detection | Done | Cross-market cluster correlation, direction detection, deduplication, signal analysis reporting |

**Decision Gate: not recorded as passed** — requires one-week live validation (< 50 alerts/day, > 60% catalyst correlation). No signal-quality results are in the repository.

### Phase 3 — Scale: Multi-Platform & PostgreSQL

| Milestone | Status | Description |
|-----------|--------|-------------|
| 3.1 — Polymarket Adapter | Done | `nexus/adapters/polymarket.py`, event normalization. Disabled by default (`POLYMARKET_ENABLED=false`) |
| 3.2 — PostgreSQL Migration | Done | `PostgresStore` (asyncpg pool), `sql/migrations/`, materialized views, `nexus db-migrate` from SQLite. Table partitioning was not implemented |
| 3.3 — Cross-Platform Correlation | Done | `nexus/correlation/cross_platform.py`, cross-platform links, retention via `RETENTION_DAYS` and `nexus prune` |

### Phase 4 — Integration: Sync & Webapp

| Milestone | Status | Description |
|-----------|--------|-------------|
| 4.1 — Sync Layer | Done, then replaced | PostgreSQL-to-Convex sync was built, then replaced on 2026-03-23 by a REST API serving an in-memory cache (see below) |
| 4.2 — Webapp Updates | Done | MarketFinder merged into this repo as `webapp/`: dashboard, markets, anomaly feed, trending topics, alerts, settings |

### Architecture changes after Phase 4

| Change | Completed | Summary |
|--------|-----------|---------|
| Kalshi API deep dive | 2026-03-20 | Dynamic WebSocket subscriptions, lifecycle channel, exchange status, candlesticks, market health score, series pattern detection, catalyst attribution, `nexus backtest` |
| REST API migration | 2026-03-23 | Broadcast data moved out of Convex into a Starlette API on Fly.io serving pre-serialized JSON from `BroadcastCache`; Convex kept for auth and per-user data. Recorded Convex bandwidth fell from 118 GB/day to near zero (`CLAUDE.md`) |
| Event-stream migration | 2026-03-27 | `EventRingBuffer` and `CandleAggregator` replaced per-tick PostgreSQL writes. Recorded results in [docs/event-stream-migration.md](docs/event-stream-migration.md) |

### Phase 5 — Intelligence: LLM Narrative Layer

Plan: [docs/phase-5-implementation-plan.md](docs/phase-5-implementation-plan.md).

| Milestone | Status | Description |
|-----------|--------|-------------|
| 5.0 — Deploy & Validate | Partial | Deployment to Fly.io, Vercel and Convex recorded on 2026-03-23; the 7-day stability observation was started but no stability report is in the repo |
| 5.1 — Template Alerts | Done (source) | `CatalystAnalyzer` wired into `DetectionLoop`; `nexus/intelligence/templates.py` renders template narratives (the control condition) |
| 5.2 — Topics & Alert Pipeline | Done (source) | `nexus/alerts/creator.py` writes per-user alerts to Convex when credentials are set; incremental re-clustering every 6h when an Anthropic key is set |
| 5.3 — LLM Narrative | Done (source) | `nexus/intelligence/llm_narrator.py` and `news.py` (Google News RSS) run alongside templates when `ANTHROPIC_API_KEY` is set; `nexus evaluate` compares the two |
| 5.4 — Hypothesis Evaluation | Pending | No evaluation results in the repository |

## Prerequisites

- Python 3.11+
- [Poetry](https://python-poetry.org/)
- Node.js and npm for `webapp/` and `convex/`

## Setup

```bash
# Install dependencies (add -E postgres for the PostgreSQL backend)
poetry install

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your Kalshi API key and private key path.
# ANTHROPIC_API_KEY enables clustering and LLM narratives, which make paid API calls.

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

# Start the full pipeline (ingestion + detection + sync + REST API on port 8080)
poetry run nexus run
poetry run nexus run --no-api      # pipeline only

# Start discovery-only polling (no WebSocket)
poetry run nexus poll

# Stream WebSocket events to console (debug)
poetry run nexus stream

# Check database statistics
poetry run nexus db-stats

# Run data integrity validation and Decision Gate check
poetry run nexus validate
```

The `sync` refresh loop that feeds the REST API cache runs only with `STORE_BACKEND=postgres`.

### Anomaly Detection

```bash
# Run a single detection cycle (single-market + cluster correlation)
poetry run nexus detect

# Run standalone cluster correlation
poetry run nexus correlate

# Build cross-platform links and run cross-platform correlation
poetry run nexus cross-platform

# List recent anomalies
poetry run nexus anomalies
poetry run nexus anomalies --anomaly-type cluster --since-hours 48

# Show anomaly signal quality statistics
poetry run nexus anomaly-stats

# Show Decision Gate signal analysis report
poetry run nexus signal-report --days 7

# Replay detection against historical data
poetry run nexus backtest

# Compare template and LLM narratives for recent anomalies
poetry run nexus evaluate --days 7
```

### Topic Clustering

```bash
# Run topic clustering on unassigned markets (requires ANTHROPIC_API_KEY)
poetry run nexus cluster
poetry run nexus cluster --mode batch

# List all topic clusters
poetry run nexus clusters --show-markets

# Show clustering quality statistics
poetry run nexus cluster-stats
```

### Market data and operations

```bash
poetry run nexus health                 # Market health scores from recent trade flow
poetry run nexus candlesticks TICKER    # OHLCV for a market
poetry run nexus taxonomy               # Kalshi category hierarchy
poetry run nexus exchange-status        # Kalshi exchange status
poetry run nexus activity               # Hourly activity (PostgreSQL view)
poetry run nexus refresh-views          # Refresh PostgreSQL materialized views
poetry run nexus db-migrate             # Copy data from SQLite to PostgreSQL
poetry run nexus prune                  # Prune old events from the event store
```

### Webapp and Convex

```bash
npm install                     # repo root: Convex + auth
npx convex dev --once           # deploy Convex schema and functions
cd webapp && npm install
npm run dev:frontend            # Vite dev server; set VITE_NEXUS_API_URL to your API
```

## Testing

```bash
poetry run pytest tests/ -v
```

Count history, kept separate from pass results:

| Source | Figure | Kind |
|--------|--------|------|
| Source tree, 2026-10-14 | 449 test functions in 33 modules (433, plus 16 in `test_postgres.py`) | Static count of `def test_` / `async def test_`; no parametrized tests |
| `CLAUDE.md` (latest recorded run) | 434 passed, 14 PostgreSQL tests skipped | Recorded run, not re-run for this update |
| `.claude/memory/MEMORY.md` (2026-03-20) | 324 passed, 14 PostgreSQL tests skipped | Recorded run |
| Earlier README (Phases 1–2) | 158 tests in 17 modules | Recorded count |

Tests are designed not to call real APIs (per `CLAUDE.md`): adapters are replaced by fakes, LLM and news calls are mocked, and stores use temporary SQLite. PostgreSQL integration tests (`@pytest.mark.postgres`) skip unless `TEST_POSTGRES_DSN` is set.

## Project Structure

```
nexus/                  Python package
  core/                 Configuration, logging, shared types
  adapters/             Platform adapters (Kalshi, Polymarket)
  ingestion/            Discovery, event bus, WebSocket manager, ring buffer, candle aggregator
  store/                Database abstraction (SQLite, PostgreSQL)
  correlation/          Windowed stats, anomaly detection, cluster/series/cross-platform correlation
  clustering/           LLM-powered topic clustering (Claude)
  intelligence/         Market health score, catalyst attribution, templates, LLM narrator, news
  alerts/               Per-user alert creation (writes to Convex)
  api/                  REST API (Starlette app, broadcast cache, uvicorn server)
  sync/                 PostgreSQL views → in-memory cache refresh; Convex client
  cli.py                Command-line interface
convex/                 Convex backend: auth, users, alerts (no broadcast data)
webapp/                 MarketFinder React frontend (Vite)
sql/                    Schema DDL and migrations
docs/                   Migration records and implementation plans
tests/                  Test suite (449 test functions)
```

### Key Components

- **EventRingBuffer** — Per-market in-memory deques holding 24h of events; the source for real-time detection
- **CandleAggregator** — Computes 1-minute OHLCV candles from the ring buffer and flushes them to the `candles` table
- **WindowComputer** — Sliding window statistics (price delta, volume, trade count), read from the ring buffer
- **AnomalyDetector** — Three detection rules: price change threshold, volume spike multiplier, Z-score breach
- **DetectionLoop** — Periodic runner for anomaly detection, cluster/series correlation and catalyst attribution
- **TopicClusterer** — LLM-based semantic clustering with batch and incremental modes
- **ClusterCorrelator** — Detects concurrent anomalies across markets in the same topic cluster
- **CatalystAnalyzer / TemplateRenderer / LLMNarrator** — Explain each anomaly from structured signals, with an optional Claude narrative
- **EventBus** — Async bounded queue with batch drain for high-throughput event ingestion
- **SyncLayer + BroadcastCache** — Refresh PostgreSQL materialized views into pre-serialized JSON served by the REST API

## Architecture

- `projectnexus_specdoc.md` — full specification and hypotheses
- `CLAUDE.md` — current architecture, data flow, infrastructure notes and conventions
- [docs/event-stream-migration.md](docs/event-stream-migration.md) — ring buffer and candle migration, with recorded results
- [docs/phase-5-implementation-plan.md](docs/phase-5-implementation-plan.md) — intelligence layer plan and deployment record
- [webapp/docs/ARCHITECTURE.md](webapp/docs/ARCHITECTURE.md) — MarketFinder design history. Its diagrams and Convex sync tables describe the pre-2026-03-23 design.


## Validation and deployment notes

**Delivered in source:**
- Kalshi REST and WebSocket ingestion
- A Polymarket adapter, which is off by default and in the checked-in `fly.toml`
- Anomaly detection with three rules over 5-minute to 24-hour windows
- Topic, series and cross-platform correlation
- Topic clustering with Claude
- SQLite and PostgreSQL stores
- An in-memory event buffer with 1-minute candles
- A 7-endpoint REST API that feeds the React webapp
- Convex for sign-in and per-user alerts only
- Template alert text and per-user alert creation
- Optional Claude-written explanations with news context, plus an `evaluate` command that compares them with the templates

**Not done:**
- The planned formal evaluation (fewer than 50 alerts a day, more than 60% tied to real catalysts, and a reader preference test of Claude-written vs template explanations) has no results in this repository.
- A 7-day stability observation began on 2026-03-23, but its planned stability report was never added.

**Deployment:**
- `docs/phase-5-implementation-plan.md` records the API on Fly.io and the dashboard on Vercel as live on 2026-03-23.
- On 2026-10-14 the dashboard root and API `/api/v1/status` each returned HTTP 200. This checks endpoint reachability, not fresh market data, pipeline health or authenticated flows.
- The most recent recorded work is the event-storage migration, completed 2026-03-27.

**What the numbers do not prove:**
- 449 counts test functions in the source (433 plus 16 PostgreSQL integration tests); it is not a pass count. The latest recorded run, in `CLAUDE.md`, is 434 passed with 14 PostgreSQL tests skipped. The suite was not re-run for this README update.
- The database-write and storage figures are recorded results from one production deployment. The raw logs are not in the repository.
- 161M is the number of cross-platform market comparisons in the original MarketFinder design. The redesign dropped that matching job in favour of anomaly detection, so the figure is not a pre-filter in the current code. The dollar figures in the same document are estimates, not billing data.
- The earlier claim of 72+ hours of stable ingestion and 100K+ events is a recorded result with no raw data in the repo. `nexus validate` re-runs the integrity and gate checks against a local database.
- Polymarket support is implemented and unit-tested but was not enabled in the recorded deployment.

## License

[Apache License 2.0](LICENSE).
