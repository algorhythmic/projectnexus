# CLAUDE.md — Project Nexus

## What Is This Project

Nexus is a **real-time prediction market intelligence engine**. It ingests streaming data from prediction market platforms (Kalshi, Polymarket), detects anomalous price/volume movements, identifies correlated shifts across semantically related markets, and surfaces structured alerts via a REST API and React webapp.

The full specification is in `projectnexus_specdoc.md` at the repo root. Always consult it for architectural decisions, API details, and phase definitions.

## Current Status

**434 tests passing** (+ 14 PostgreSQL integration tests that skip without `TEST_POSTGRES_DSN`)

**Completed milestones:**
- Phase 1: Kalshi REST adapter, WebSocket streaming, stability monitoring (Milestones 1.1–1.3)
- Phase 2: Anomaly detection, topic clustering, cluster correlation (Milestones 2.1–2.3)
- Phase 3: Polymarket adapter, PostgreSQL migration, cross-platform correlation (Milestones 3.1–3.3)
- Phase 4: Convex sync layer → **replaced by REST API** (see Architecture Migration below)
- Fly.io deployment: Running on `shared-cpu-1x` (1GB RAM), Kalshi production mode + REST API on port 8080
- MarketFinder webapp wired to Nexus REST API for broadcast data, Convex for auth only

**Architecture migration (completed 2026-03-23):**
- Convex reactive queries caused $17/day (118 GB) in bandwidth to display ~10 rows
- Root cause: broadcast data (identical for all users) stored as individual Convex documents with reactive query amplification
- **Fix:** REST API on Fly.io serving pre-computed data from in-memory cache. Webapp polls via fetch instead of Convex reactive queries
- Convex now handles **auth + per-user features only** (users, alerts, preferences)
- Broadcast data sync tables removed from Convex
- Convex bandwidth dropped from 118 GB/day to near zero

**Event-stream migration (completed 2026-03-27):**
- PG was growing at 3.5 GB/month from 487K events/day (90% `price_change` events consumed only in sliding windows)
- **Fix:** In-memory `EventRingBuffer` replaces PG for real-time analysis. `CandleAggregator` computes 1-minute OHLCV candles in memory and flushes to a `candles` table. `price_change` events no longer written to PG.
- PG writes dropped from ~487K/day to ~50K/day (99% reduction for price events)
- DB size dropped from 746 MB to 38 MB. Growth rate: ~12 MB/day (was 120 MB/day)
- Supabase free tier viable for months (was exceeding 500 MB limit)
- Detection reads from ring buffer (zero-latency, no PG I/O per detection cycle)
- Feature flag: `PERSIST_PRICE_CHANGE_EVENTS` (default false) for rollback
- Full spec: `docs/event-stream-migration.md`
- **Future:** Raw event archive via Tigris/R2 object storage if backtesting against raw events is needed (see deferred Step 7 in migration doc)

**Operational work completed:**
- Anomaly thresholds tuned for prediction markets (3% price, 2x volume, 1.5 z-score)
- Anomaly summaries enriched with market titles and price from/to
- Logarithmic severity scaling (was linear, all anomalies capped at 1.00)
- Anomaly deduplication (skip markets with existing active anomalies)
- Discovery filtered: exclude combo markets (`mve_filter`), near-expiry (`min_close_ts`)
- OOM fix: detection capped at 200 markets/cycle (configurable), init from 10min ago
- RSS memory monitoring: `rss_mb` in pipeline health logs (every 60s)
- Kalshi adapter updated for Jan–Mar 2026 API field migration (`_dollars`/`_fp` suffixes)
- Market prices written directly to `markets.yes_price` (no more events LATERAL JOIN)

**Kalshi API deep dive (completed 2026-03-20):**
- Dynamic WS subscriptions (`update_subscription` — no reconnect needed for new tickers)
- Lifecycle v2 channel (`market_lifecycle_v2` — instant new-market detection)
- Exchange health awareness (`get_exchange_status`, `get_exchange_schedule`)
- Candlestick charts (REST API endpoint + TradingView `lightweight-charts` React component)
- Market intelligence health score (5-signal in-memory synthesis)
- Series pattern detection (coordinated moves across same-series markets)
- Catalyst attribution (structured CatalystAnalysis for Phase 5 LLM prompts)
- Category taxonomy, single market lookup, orderbook depth, trade flow, milestones REST methods
- Backtest CLI (`nexus backtest` replays detection against historical data)

**Next milestones (see `docs/phase-5-implementation-plan.md` for full details):**

- **Milestone 5.0 — Deploy & Validate:** Deploy REST API (`fly deploy`), webapp (Vercel), Convex schema (`npx convex dev --once`). Run 7-day stability observation to validate Hypothesis A baselines and verify OOM fixes hold during peak hours.
- **Milestone 5.1 — Template Alerts:** Wire `CatalystAnalyzer` into `DetectionLoop` (currently unconnected). Build template renderer (`nexus/intelligence/templates.py`) to produce human-readable narratives from structured catalyst data. Enrich `/api/v1/anomalies` response with `catalyst` field. This is the **control condition** for Hypothesis C.
- **Milestone 5.2 — Topics & Alert Pipeline:** Run initial topic clustering (`nexus cluster`, requires `ANTHROPIC_API_KEY`). Add incremental re-clustering trigger in detection loop (every 6h). Build alert creation bridge: Python → Convex `alerts` table, matching anomalies to user preferences.
- **Milestone 5.3 — LLM Narrative:** Integrate news API (Google News RSS). Build Claude-powered narrative generator (`nexus/intelligence/llm_narrator.py`). Run template + LLM in parallel for A/B comparison. Add `nexus evaluate` CLI command.
- **Milestone 5.4 — Hypothesis Evaluation:** Formal evaluation of Hypotheses A (stability), B (signal quality: <50 alerts/day, >60% real catalysts), C (LLM preferred 70%+ over templates). Track 2 decision gate.

## Repository Layout (Monorepo)

```
projectnexus/                   # Git root — monorepo
├── nexus/                      # Python package (data pipeline + REST API)
│   ├── core/                   # config.py, logging.py, types.py
│   ├── adapters/               # auth.py, base.py, kalshi.py, polymarket.py
│   ├── ingestion/              # discovery.py, bus.py, manager.py, metrics.py, ring_buffer.py, candle_aggregator.py
│   ├── store/                  # base.py, sqlite.py, postgres.py, __init__.py (factory)
│   ├── correlation/            # detector, correlator, cross_platform, series_detector
│   ├── intelligence/           # health.py (market health score), narrative.py (catalyst attribution)
│   ├── api/                    # REST API: cache.py, app.py (Starlette), server.py (uvicorn)
│   ├── sync/                   # sync.py (PG views → BroadcastCache refresh loop)
│   └── cli.py
├── convex/                     # Convex backend (auth + per-user features only)
│   ├── schema.ts               # users + alerts tables (NO broadcast data)
│   ├── auth.ts, users.ts       # Auth + user preferences/alerts
│   └── crons.ts, http.ts       # Stubs
├── webapp/                     # MarketFinder React frontend
│   ├── src/
│   │   ├── components/         # UI components (Dashboard, Markets, Anomalies, etc.)
│   │   ├── hooks/              # use-nexus-query.ts (REST polling), use-debounce.ts
│   │   ├── lib/                # nexus-api.ts (fetch wrapper)
│   │   └── types/              # nexus.ts (NexusMarket, NexusAnomaly, etc.)
│   ├── package.json            # React/Vite/UI deps
│   └── vite.config.ts
├── sql/                        # PG schema, migrations/
├── tests/                      # pytest suite
├── package.json                # Root — convex + @convex-dev/auth only
├── Dockerfile                  # Python-only Fly.io image (exposes port 8080)
├── fly.toml                    # Fly.io config (worker + http_service)
├── pyproject.toml              # Poetry config
└── CLAUDE.md                   # This file
```

The `marketfinder-main/` and `marketfinder_ETL-main/` directories are gitignored reference repos used during porting.

## Tech Stack

### Nexus (Python data pipeline + REST API)
- **Python 3.11+** — `pyproject.toml` targets `^3.11`
- **Poetry** for dependency management
- **Starlette** + **uvicorn** for the REST API (runs in the same asyncio event loop as the pipeline)
- **aiosqlite** for async SQLite (Phase 1 store)
- **asyncpg** for async PostgreSQL (Phase 2+ store, with connection pooling)
- **httpx** for async HTTP
- **websockets** for WebSocket connections
- **cryptography** for RSA-PSS signing (Kalshi auth)
- **pydantic** + **pydantic-settings** for config and data models
- **structlog** for structured JSON logging
- **typer** + **rich** for CLI
- **pytest** + **pytest-asyncio** for testing

### MarketFinder (React webapp — `webapp/`)
- **React 18.2.0** with **Vite 6.2.0**
- **Convex ^1.24.2** for auth only (Password + Anonymous providers via `@convex-dev/auth`)
- **Nexus REST API** for all broadcast data (markets, anomalies, stats, topics, candlesticks)
- **TanStack React Table 8.21.3** for data tables
- **Tailwind CSS** with neobrutalist design system
- **lightweight-charts 5.x** (TradingView) for OHLCV candlestick charts
- **lucide-react** for icons, **Radix UI** primitives, **shadcn/ui** component library

## Data Architecture

### Broadcast data (REST API — same for all users)
PostgreSQL materialized views → SyncLayer refreshes in-memory BroadcastCache → Starlette serves JSON with Cache-Control headers. **Zero database queries per HTTP request.**

| Endpoint | Source View | Refresh | Cache TTL |
|---|---|---|---|
| `/api/v1/markets` | `v_current_market_state` | 60s | 30s |
| `/api/v1/markets/stats` | Pre-computed from market cache | 60s | 30s |
| `/api/v1/anomalies` | `v_active_anomalies` | 60s | 30s |
| `/api/v1/anomalies/stats` | Pre-computed from anomaly cache | 60s | 30s |
| `/api/v1/topics` | `v_trending_topics` | 10min | 120s |
| `/api/v1/candlesticks/{ticker}` | `candles` table → `compute_candlesticks()` fallback → Kalshi API | On demand | 60s |
| `/api/v1/status` | Cache metadata | Instant | 10s |

### Per-user data (Convex — different per user)
- Auth (sessions, accounts) — `@convex-dev/auth` library
- User preferences (categories, platforms, notification toggles) — `users` table
- User alerts (per-user notification feed) — `alerts` table

### Why this split
Convex's reactive model amplifies bandwidth linearly per connected client for shared data. REST + caching makes serving cost **independent of user count**. See `feedback_convex_misuse.md` in `.claude/memory/` for the full post-mortem.

## Code Conventions

### Architecture Patterns
- **BaseAdapter ABC** (`nexus/adapters/base.py`): All platform adapters implement `discover()` (REST polling) and `connect()` (WebSocket streaming). The base class provides `RateLimiter`, `make_request()` with retry/backoff, and httpx client management.
- **BaseStore ABC** (`nexus/store/base.py`): Database abstraction. SQLiteStore (Phase 1) and PostgresStore (Phase 2+) both implement it. Use `create_store(settings)` factory from `nexus/store/__init__.py`.
- **BroadcastCache** (`nexus/api/cache.py`): In-memory dict of pre-serialized JSON entries with ETag support. Updated by SyncLayer, served by Starlette. Stats (market counts, anomaly severity buckets) are pre-computed during cache update, not per request.
- **SyncLayer** (`nexus/sync/sync.py`): Refreshes PG materialized views on a timer and populates BroadcastCache. Runs as an asyncio TaskGroup task alongside ingestion, detection, and the API server.
- **LoggerMixin** (`nexus/core/logging.py`): All classes that need logging inherit from this mixin to get a `.logger` property.
- **Settings singleton** (`nexus/core/config.py`): Pydantic BaseSettings with `.env` file support. Import as `from nexus.core.config import settings`.
- **EventBus** (`nexus/ingestion/bus.py`): Bounded `asyncio.Queue` with batch drain worker. Routes events to: ring buffer (all events), PG (trade/status/new_market only — price_change filtered out), and market price shadow-write.
- **EventRingBuffer** (`nexus/ingestion/ring_buffer.py`): Per-market bounded deques holding 24h of events in memory. Source of truth for real-time detection and candle aggregation. ~400 bytes/event, cleanup every 5 min.
- **CandleAggregator** (`nexus/ingestion/candle_aggregator.py`): Reads price_change + trade events from ring buffer, computes 1-minute OHLCV candles, flushes to PG `candles` table every 30s. Replaces `compute_candlesticks()` SQL function.
- **IngestionManager** (`nexus/ingestion/manager.py`): TaskGroup orchestrates discovery + streaming concurrently.
- **MarketHealthTracker** (`nexus/intelligence/health.py`): In-memory rolling windows that synthesize trade flow, orderbook depth, and momentum into a per-market 0–1 health score. Fed by IngestionManager, consumed by SyncLayer.
- **SeriesPatternDetector** (`nexus/correlation/series_detector.py`): Detects when 3+ markets in a series move together in a time window. Runs in DetectionLoop after single-market detection.
- **CatalystAnalyzer** (`nexus/intelligence/narrative.py`): Gathers contextual signals to explain anomalies. Outputs structured `CatalystAnalysis` dataclass ready for Phase 5 LLM prompts.

### Naming
- Pydantic models for shared types live in `nexus/core/types.py`: `Platform`, `EventType`, `MarketRecord`, `EventRecord`, `DiscoveredMarket`
- Platform-specific code stays in adapters (e.g., category mapping, price normalization)
- Use `field_validator` (not deprecated `validator`) for Pydantic v2

### Async
- All I/O operations are async (aiosqlite, httpx, asyncpg)
- CLI commands wrap async functions with `asyncio.run()`
- The Fly.io process runs 4 concurrent tasks in an `asyncio.TaskGroup`: ingestion, detection, sync (cache refresh), and API server
- Tests use `pytest-asyncio` with `asyncio_mode = "auto"`

### Error Handling
- Adapters retry on 5xx and 429 with exponential backoff; raise immediately on other 4xx
- The discovery loop catches adapter errors per-adapter and continues with the next
- Rate limiting is enforced at the adapter level via `RateLimiter`

### Testing
- Run: `poetry run pytest tests/ -v` (or `python -m poetry run pytest tests/ -v` on Windows)
- Fixtures in `tests/conftest.py`: `tmp_store` (temp SQLite), `pg_store` (PostgreSQL, skips without `TEST_POSTGRES_DSN`), `rsa_key_pair` (ephemeral RSA keys), `sample_settings`
- Tests do NOT hit real APIs — use FakeAdapter/FakeStreamingAdapter pattern and temp databases
- Bus tests need a real market in DB (FK constraint) — use `_insert_market()` helper
- PostgreSQL integration tests use `@pytest.mark.postgres` marker
- API tests use Starlette's `TestClient` with a mock `BroadcastCache`

### Webapp Conventions (`webapp/`)

**Routing:** State-based via `Dashboard.tsx`. The `activeView` string determines which component renders. Views: `dashboard`, `markets`, `topics`, `anomalies`, `alerts`, `settings`. No React Router.

**Data fetching (broadcast):** `useNexusQuery<T>(path, params?, options?)` hook polls the REST API with stale-while-revalidate. Returns `{ data, isLoading, error }`. Data is `undefined` while loading the first fetch. Uses `VITE_NEXUS_API_URL` env var (fallback: `https://projectnexus.fly.dev`).

**Data fetching (per-user):** Convex `useQuery` for auth, alerts, preferences. Only used in `NeobrutalistSidebar.tsx`, `AlertsView.tsx`, `SettingsView.tsx`.

**Types:** Broadcast data uses local interfaces in `webapp/src/types/nexus.ts` (`NexusMarket`, `NexusAnomaly`, `NexusTopic`, etc.). Per-user data uses Convex `Doc<>` types.

**Design system (Neobrutalist):** Borders: `border-4 border-black`. Shadows: `shadow-[8px_8px_0px_0px_#000]`. Bold fills: `bg-yellow-300`, `bg-green-300`, `bg-red-300`, `bg-blue-300`. Dark mode: `dark:` Tailwind modifier throughout.

**Severity color scale:** High (>=0.7): `bg-red-300`/`bg-red-700`. Medium (>=0.4): `bg-yellow-300`/`bg-yellow-600`. Low (<0.4): `bg-blue-300`/`bg-blue-700`.

**Auth:** `@convex-dev/auth` with Password + Anonymous providers. `getAuthUserId(ctx)` server-side. Auth tables managed by the library — don't modify directly.

### Convex Schema (`convex/schema.ts`)

**App-owned tables (auth + per-user only):**
- `users` — preferences (categories, platforms, notification toggles)
- `alerts` — user notifications (anomaly, price_change, new_market types)
- Auth tables (`authSessions`, `authAccounts`, etc.) — managed by `@convex-dev/auth`

**No broadcast data in Convex.** Markets, anomalies, topics, summaries, and candlesticks are served by the Nexus REST API.

## Key API Details

### Kalshi
- **Production:** `https://api.elections.kalshi.com/trade-api/v2`
- **Demo/Sandbox:** `https://demo-api.kalshi.co/trade-api/v2` (default, safe for development)
- **Auth:** RSA-PSS SHA-256 — message is `timestamp_ms + METHOD + path`, three headers: `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP`, `KALSHI-ACCESS-SIGNATURE`
- **Rate limits (Basic tier):** 20 reads/sec, 10 writes/sec — we default to 15 reads/sec for safety
- **Pagination:** Cursor-based (`cursor` param in response), not page-number based
- **WebSocket:** `wss://api.elections.kalshi.com/trade-api/ws/v2`
- **Discovery filters:** `mve_filter=exclude` (skip combo markets), `min_close_ts` (skip near-expiry), 20 pages max (4000 markets/cycle)
- **Data model:** Series → Events → Markets hierarchy. `series_ticker` groups recurring markets
- **~4,000+ active non-combo markets**, defined trading hours (most active 9:30 AM–8 PM ET)
- **Field naming (Jan–Mar 2026 migration):** Prices use `_dollars` suffix (FixedPointDollars strings, e.g. `"0.6500"`). Counts use `_fp` suffix (FixedPointCount strings, e.g. `"10.00"`). Legacy integer fields removed Mar 12, 2026.
- **`"0.0000"` gotcha:** FixedPointDollars strings like `"0.0000"` are truthy in Python but mean "no data." Use explicit `float(val) > 0` checks. See `_calculate_yes_price()` in `kalshi.py`.
- **WebSocket channels:** `ticker` (price updates), `trade` (individual trades), `market_lifecycle_v2` (market + event lifecycle). Private channels (orderbook_delta, fill) require authenticated WS.
- **Dynamic WS subscriptions:** `update_subscription` command with `action: "add_markets"` / `"delete_markets"` adds/removes tickers without reconnecting.
- **Market statuses:** `initialized`, `inactive`, `active`, `closed`, `determined`, `disputed`, `amended`, `finalized` (no "open" status)

### Polymarket
- **REST:** `https://gamma-api.polymarket.com`
- **CLOB WebSocket:** `wss://ws-subscriptions-clob.polymarket.com`
- **RTDS WebSocket:** `wss://ws-live-data.polymarket.com`
- **Auth:** EIP-712 wallet signatures (L1) + HMAC-SHA256 API credentials (L2)
- **Rate limits:** ~100 req/min free, $99/mo premium for WS feeds
- **~1,000+ active markets**, 24/7

### API Limitation
Neither platform offers a firehose webhook. Both require periodic REST polling (30–60s) to discover new markets, plus WebSocket subscriptions for real-time updates on tracked markets.

## Database Schema

Defined in `sql/schema.sql`, `sql/migrations/`, and inline in store implementations.

**Core tables:**
- `markets` — UNIQUE(platform, external_id), includes `yes_price` and `price_updated_at` columns (shadow-written by EventBus)
- `events` — FK to markets. **Only trade, new_market, status_change, volume_update events persisted** (price_change goes to ring buffer only since event-stream migration)
- `candles` — pre-computed 1-minute OHLCV from CandleAggregator. UNIQUE(market_id, interval, open_ts)

**Phase 2 tables:** `topic_clusters`, `market_cluster_memberships`, `anomalies`, `anomaly_markets`

**PostgreSQL specifics:**
- BIGSERIAL primary keys, `$1/$2/$3` numbered params (not `?`)
- `INSERT ... ON CONFLICT DO UPDATE` for upserts (not `INSERT OR REPLACE`, to preserve ID stability)
- 5 materialized views: `v_current_market_state` (reads from `markets.yes_price`, not events), `v_active_anomalies`, `v_trending_topics`, `v_market_summaries`, `v_hourly_activity`
- `compute_candlesticks()` still exists as legacy fallback but primary source is the `candles` table
- Connection pooling via `asyncpg.create_pool()`
- DB size: ~38 MB, growth rate: ~12 MB/day (was 120 MB/day before event-stream migration)

## Relationship: Nexus ↔ MarketFinder (Monorepo)

This is a **monorepo** containing the data pipeline (`nexus/`), the REST API (`nexus/api/`), and the webapp (`webapp/`).

- **Nexus** (`nexus/`): Python data pipeline + REST API. Source of truth for all market data. Serves broadcast data via REST endpoints from in-memory cache.
- **MarketFinder** (`webapp/`): React webapp. Reads broadcast data from Nexus REST API, per-user data from Convex.
- **Convex** (`convex/`): Auth + per-user features only. No broadcast data.
- **MarketFinder ETL** (`marketfinder_ETL-main/`): **Deprecated.** Reference repo only (gitignored).

## Infrastructure

- **GitHub repo:** `algorhythmic/projectnexus`
- **Supabase:** PostgreSQL host (use direct connection port 5432, NOT PgBouncer 6543)
- **Fly.io:** DEPLOYED (`shared-cpu-1x`, 1GB RAM, app `projectnexus`). Runs pipeline + REST API on port 8080. IPs: shared IPv4 + dedicated IPv6. Off-peak RSS: ~78MB, post-discovery: ~156MB. Deploy with `fly deploy` from repo root.
- **Convex:** `deafening-starling-749` — auth + per-user features only. Cloud URL: `https://deafening-starling-749.convex.cloud`. Deploy with `npx convex dev --once` from repo root.
- **Vercel:** Webapp deployment. Set `VITE_NEXUS_API_URL=https://projectnexus.fly.dev` in environment settings. Auto-deploys from `main` branch.
- **Containerized auth:** Inline PEM key support via `KALSHI_PRIVATE_KEY_PEM` env var (for Fly.io where key file isn't available)

## Environment Notes

This is a multi-machine project. Check your local environment before assuming tool availability.

### Common
- `pyproject.toml` targets Python `^3.11`
- Poetry for dependency management
- Git identity: `algorhythmic` / `algorhythmic@users.noreply.github.com`

### Windows (primary dev machine)
- Windows 11, Git Bash shell
- Python 3.13 (Microsoft Store)
- Poetry invoked as `python -m poetry` (not on PATH directly)
- Poetry venvs configured as in-project (`.venv/`) to avoid long-path issues
- `gh` CLI is NOT installed — use git commands directly

### macOS (secondary)
- macOS (Darwin), zsh shell
- Python 3.12.4 (Anaconda at `/opt/anaconda3/bin/python3`)
- Poetry 2.3.2 on PATH as `poetry`
- `gh` CLI available (`/opt/homebrew/bin/gh`)
- `fly` CLI available (`/opt/homebrew/bin/fly`)

## Commands Reference

```bash
# ─── Python (from repo root) ───
poetry install                          # Install deps (macOS)
python -m poetry install                # Install deps (Windows)
poetry run pytest tests/ -v             # Run tests
poetry run nexus info                   # Show config
poetry run nexus run                    # Start pipeline + REST API
poetry run nexus run --no-api           # Pipeline only (no REST server)
poetry run nexus discover               # One-shot discovery cycle
poetry run nexus detect                 # One-shot detection cycle
poetry run nexus db-stats               # Market/event counts
poetry run nexus refresh-views          # Refresh PostgreSQL materialized views
poetry run nexus health                 # Show market health scores from trade flow
poetry run nexus backtest               # Replay detection against historical data
poetry run nexus candlesticks TICKER    # Fetch OHLCV for a market
poetry run nexus taxonomy               # Display Kalshi category hierarchy
poetry run nexus exchange-status        # Check exchange operational status

# ─── Convex (from repo root) ───
npm install                             # First time only
npx convex dev --once                   # Deploy schema + functions

# ─── Webapp (from webapp/) ───
cd webapp && npm install                # First time only
npm run dev:frontend                    # Vite dev server
npx vite build                          # Production build
npx tsc --noEmit                        # Type check

# ─── Deploy ───
npx convex dev --once                   # 1. Deploy Convex (auth schema)
fly deploy                              # 2. Deploy Nexus pipeline + API to Fly.io
# Vercel auto-deploys from main branch

# ─── REST API (test locally) ───
curl http://localhost:8080/api/v1/status
curl 'http://localhost:8080/api/v1/markets?limit=10&sort=rank_score'
curl 'http://localhost:8080/api/v1/anomalies?min_severity=0.7'
```

## Anomaly Detection Tuning

Thresholds were calibrated on 2026-03-18 for prediction market data:
- `ANOMALY_PRICE_CHANGE_THRESHOLD`: 0.03 (3%) — prediction markets are 0-1 bounded, typical moves 1-3%
- `ANOMALY_VOLUME_SPIKE_MULTIPLIER`: 2.0
- `ANOMALY_ZSCORE_THRESHOLD`: 1.5
- **Severity:** Logarithmic scaling (`log10(ratio+1)/log10(101)`) — 2x threshold → 0.15, 5x → 0.35, 100x → 1.0
- **Deduplication:** Markets with existing active anomalies are skipped (single SQL JOIN query)
- **Series detection:** 3+ markets in the same series moving >3% in the same direction within 30min triggers a cluster anomaly
- **Health score weights:** velocity=0.25, imbalance=0.20, whale=0.20, spread=0.15, momentum=0.20
- **Known:** Only 1440min window anomalies fire during off-hours; short windows need peak-hour activity. Topic clusters empty until `nexus cluster` is run (requires ANTHROPIC_API_KEY).

## Infrastructure Gotchas

- **Supabase 500MB limit:** Was at 746 MB before event-stream migration. Now 38 MB with ~12 MB/day growth. price_change events no longer written to PG. Stale markets and historical price_change events purged.
- **Fly.io 1GB RAM:** Detection reads from in-memory ring buffer (no PG I/O). CandleAggregator and ring buffer add ~30-50 MB to RSS at steady state. Off-peak RSS: ~110-125 MB. Monitor `rss_mb` and `ring_buffer.memory_estimate_mb` in `/api/v1/status`.
- **Convex is for per-user data only.** Never use Convex to serve broadcast data (identical for all users). Reactive queries amplify bandwidth linearly per connected client. Use REST + caching instead. This lesson cost $17 in one day.
- **Always verify external API responses** before coding against them — docs and existing code may reference stale field names (learned from the Jan 2026 `_dollars` migration).
- **Fly.io IP allocation:** The app needs explicit IP allocation for HTTP services (`fly ips allocate-v4 --shared`, `fly ips allocate-v6`). Without IPs, the domain won't resolve.

## Important Warnings

- **Never commit `.env` or `.env.local` files** — they contain API keys and deployment targets.
- **Default to demo mode** (`KALSHI_USE_DEMO=true`) to avoid hitting production rate limits during development.
- **Don't add heavy dependencies** without checking the spec.
- **Don't break existing implementations.** Phases 1–4 are complete — understand existing code before modifying.
- **Don't store broadcast data in Convex.** Use the REST API for data that's the same for all users.
- **Don't add cron jobs** to `convex/crons.ts` — all data ingestion happens in Nexus on Fly.io.
- **Auth tables** (`authSessions`, `authAccounts`, etc.) are managed by `@convex-dev/auth` — don't modify them directly.
