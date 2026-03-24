# CLAUDE.md — Project Nexus

## What Is This Project

Nexus is a **real-time prediction market intelligence engine**. It ingests streaming data from prediction market platforms (Kalshi, Polymarket), detects anomalous price/volume movements, identifies correlated shifts across semantically related markets, and surfaces structured alerts.

The full specification is in `projectnexus_specdoc.md` at the repo root. Always consult it for architectural decisions, API details, and phase definitions.

## Current Status

**324 tests passing** (+ 14 PostgreSQL integration tests that skip without `TEST_POSTGRES_DSN`)

**Completed milestones:**
- Phase 1: Kalshi REST adapter, WebSocket streaming, stability monitoring (Milestones 1.1–1.3)
- Phase 2: Anomaly detection, topic clustering, cluster correlation (Milestones 2.1–2.3)
- Phase 3: Polymarket adapter, PostgreSQL migration, cross-platform correlation (Milestones 3.1–3.3)
- Phase 4, Milestone 4.1: Convex sync layer (PostgreSQL → Convex via HTTP API)
- Fly.io deployment: Running on `shared-cpu-1x` (1GB RAM), Kalshi production mode
- Phase 4, Milestone 4.2: MarketFinder webapp wired to Nexus-synced Convex tables

**Operational work completed:**
- Anomaly thresholds tuned for prediction markets (3% price, 2x volume, 1.5 z-score)
- Anomaly summaries enriched with market titles and price from/to
- Logarithmic severity scaling (was linear, all anomalies capped at 1.00)
- Anomaly deduplication (skip markets with existing active anomalies)
- Discovery filtered: exclude combo markets (`mve_filter`), near-expiry (`min_close_ts`)
- Sync optimized: only markets with events synced to Convex (now 1000 vs 90K+)
- OOM fix: detection capped at 200 markets/cycle (configurable), init from 10min ago
- DB cleanup: stale markets purged, awaiting Supabase autovacuum
- RSS memory monitoring: `rss_mb` in pipeline health logs (every 60s), `rss_before/after/delta_mb` in detection cycle logs
- `nexus detect` enhanced with `--lookback` and `--cap` flags for instant local profiling
- Kalshi adapter updated for Jan–Mar 2026 API field migration (`_dollars`/`_fp` suffixes)
- Discovery first-cycle now emits `price_change` events (was silently seeding cache only)
- First-seen markets emit both `new_market` + `price_change` events (view needs `price_change`)
- Convex stale market cleanup: `cleanupStaleMarkets` mutation, throttled to every 5 min
- Materialized view refresh bug fixed: `v_current_market_state` now refreshes every 5 min (was only on startup)

**Kalshi API deep dive (completed 2026-03-20):**
- Dynamic WS subscriptions (`update_subscription` — no reconnect needed for new tickers)
- Lifecycle v2 channel (`market_lifecycle_v2` — instant new-market detection via event_lifecycle)
- Exchange health awareness (`get_exchange_status`, `get_exchange_schedule`)
- Candlestick charts (Convex caching proxy + TradingView `lightweight-charts` React component)
- Market intelligence health score (5-signal in-memory synthesis: velocity, imbalance, whale, spread, momentum)
- Series pattern detection (coordinated moves across same-series markets)
- Catalyst attribution (structured CatalystAnalysis for Phase 5 LLM prompts)
- Category taxonomy, single market lookup, orderbook depth, trade flow, milestones REST methods
- Backtest CLI (`nexus backtest` replays detection against historical data)

**Next milestones:**
- Deploy Convex schema (`npx convex dev --once`) for candlestickCache + healthScore + candlesticks action
- Deploy Fly.io (`fly deploy`) for health tracker + series detector + new REST methods
- Verify OOM fixes hold during peak hours (check `rss_mb` in fly logs 9:30 AM–8 PM ET)
- Run initial topic clustering (`nexus cluster`) to enable trending topics
- Phase 5: LLM narrative layer (catalyst attribution foundation is ready)

## Repository Layout (Monorepo)

```
projectnexus/                   # Git root — monorepo
├── nexus/                      # Python package (data pipeline)
│   ├── core/                   # config.py, logging.py, types.py
│   ├── adapters/               # auth.py, base.py, kalshi.py, polymarket.py
│   ├── ingestion/              # discovery.py, bus.py, manager.py, metrics.py
│   ├── store/                  # base.py, sqlite.py, postgres.py, __init__.py (factory)
│   ├── correlation/            # detector, correlator, cross_platform, series_detector
│   ├── intelligence/           # health.py (market health score), narrative.py (catalyst attribution)
│   ├── sync/                   # convex_client.py, sync.py
│   └── cli.py
├── convex/                     # Convex backend (single source of truth)
│   ├── schema.ts               # All tables: sync targets + webapp-owned + candlestickCache
│   ├── nexusSync.ts            # Mutations called by Python sync layer
│   ├── candlesticks.ts         # Convex action: Kalshi API proxy with 60s cache
│   ├── queries.ts              # Read queries for React components
│   └── auth.ts, users.ts, ... # Webapp-specific Convex functions
├── webapp/                     # MarketFinder React frontend
│   ├── src/                    # Components, hooks, pages
│   ├── package.json            # React/Vite/UI deps
│   └── vite.config.ts
├── sql/                        # PG schema, migrations/
├── tests/                      # pytest suite
├── package.json                # Root — convex + @convex-dev/auth only
├── Dockerfile                  # Python-only Fly.io image
├── fly.toml                    # Fly.io config
├── pyproject.toml              # Poetry config
└── CLAUDE.md                   # This file
```

The `marketfinder-main/` and `marketfinder_ETL-main/` directories are gitignored reference repos used during porting. The original MarketFinder repo (`github.com/algorhythmic/marketfinder`) has been merged into this monorepo under `webapp/`.

## Tech Stack

### Nexus (Python data pipeline)
- **Python 3.11+** (currently running 3.13 on this machine)
- **Poetry** for dependency management (`python -m poetry` — not on PATH directly)
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
- **Convex ^1.24.2** for reactive backend (queries, mutations, auth)
- **@convex-dev/auth ^0.0.80** with Password + Anonymous providers
- **TanStack React Table 8.21.3** for data tables
- **Tailwind CSS** with neobrutalist design system
- **lightweight-charts 5.x** (TradingView) for OHLCV candlestick charts
- **lucide-react** for icons, **Radix UI** primitives, **shadcn/ui** component library

## Code Conventions

### Architecture Patterns
- **BaseAdapter ABC** (`nexus/adapters/base.py`): All platform adapters implement `discover()` (REST polling) and `connect()` (WebSocket streaming). The base class provides `RateLimiter`, `make_request()` with retry/backoff, and httpx client management.
- **BaseStore ABC** (`nexus/store/base.py`): Database abstraction. SQLiteStore (Phase 1) and PostgresStore (Phase 2+) both implement it. Use `create_store(settings)` factory from `nexus/store/__init__.py`.
- **LoggerMixin** (`nexus/core/logging.py`): All classes that need logging inherit from this mixin to get a `.logger` property.
- **Settings singleton** (`nexus/core/config.py`): Pydantic BaseSettings with `.env` file support. Import as `from nexus.core.config import settings`.
- **EventBus** (`nexus/ingestion/bus.py`): Bounded `asyncio.Queue` with batch drain worker for backpressure.
- **IngestionManager** (`nexus/ingestion/discovery.py`): TaskGroup orchestrates discovery + streaming concurrently.
- **MetricsCollector** (`nexus/core/`): In-memory metrics with rolling throughput window. ErrorCategory enum tracks ws_disconnect, rate_limit_hit, etc.
- **MarketHealthTracker** (`nexus/intelligence/health.py`): In-memory rolling windows that synthesize trade flow, orderbook depth, and momentum into a per-market 0–1 health score. No DB tables — purely in-memory with `deque` windows. Fed by IngestionManager, consumed by SyncLayer.
- **SeriesPatternDetector** (`nexus/correlation/series_detector.py`): Detects when 3+ markets in a series (same ticker prefix) move together in a time window. Runs in DetectionLoop after single-market detection.
- **CatalystAnalyzer** (`nexus/intelligence/narrative.py`): Gathers contextual signals (trade burst, whale %, taker imbalance) to explain anomalies. Outputs structured `CatalystAnalysis` dataclass ready for Phase 5 LLM prompts.

### Naming
- Pydantic models for shared types live in `nexus/core/types.py`: `Platform`, `EventType`, `MarketRecord`, `EventRecord`, `DiscoveredMarket`
- Platform-specific code stays in adapters (e.g., category mapping, price normalization)
- Use `field_validator` (not deprecated `validator`) for Pydantic v2

### Async
- All I/O operations are async (aiosqlite, httpx)
- CLI commands wrap async functions with `asyncio.run()`
- Tests use `pytest-asyncio` with `asyncio_mode = "auto"` — async test functions run automatically

### Error Handling
- Adapters retry on 5xx and 429 with exponential backoff; raise immediately on other 4xx
- The discovery loop catches adapter errors per-adapter and continues with the next
- Rate limiting is enforced at the adapter level via `RateLimiter`

### Testing
- Run: `python -m poetry run pytest tests/ -v`
- Fixtures in `tests/conftest.py`: `tmp_store` (temp SQLite), `pg_store` (PostgreSQL, skips without `TEST_POSTGRES_DSN`), `rsa_key_pair` (ephemeral RSA keys), `sample_settings`
- Tests do NOT hit real APIs — use FakeAdapter/FakeStreamingAdapter pattern and temp databases
- Bus tests need a real market in DB (FK constraint) — use `_insert_market()` helper
- PostgreSQL integration tests use `@pytest.mark.postgres` marker

### Webapp Conventions (`webapp/`)

**Routing:** State-based via `Dashboard.tsx`. The `activeView` string determines which component renders. Views: `dashboard`, `markets`, `topics`, `anomalies`, `alerts`, `settings`. No React Router.

**Data fetching:** All data comes from Convex reactive queries (`useQuery`). Results may be `undefined` while loading — always handle loading states.

**Design system (Neobrutalist):** Borders: `border-4 border-black`. Shadows: `shadow-[8px_8px_0px_0px_#000]`. Bold fills: `bg-yellow-300`, `bg-green-300`, `bg-red-300`, `bg-blue-300`. Dark mode: `dark:` Tailwind modifier throughout.

**Severity color scale:** High (>=0.7): `bg-red-300`/`bg-red-700`. Medium (>=0.4): `bg-yellow-300`/`bg-yellow-600`. Low (<0.4): `bg-blue-300`/`bg-blue-700`.

**Auth:** `@convex-dev/auth` with Password + Anonymous providers. `getAuthUserId(ctx)` server-side. Auth tables managed by the library — don't modify directly.

**Playwright:** `npx playwright screenshot http://localhost:5173 screenshot.png` for visual verification. Use `--wait-for-timeout=3000` for async data.

### Convex Schema (`convex/schema.ts`)

**Sync tables (populated by Nexus, read-only for webapp):**
- `nexusMarkets` — market data with price/volume/healthScore, indexed by platform/active/search
- `activeAnomalies` — detected anomalies with severity/type
- `trendingTopics` — topic clusters ranked by anomaly activity
- `marketSummaries` — aggregated market event statistics

**Cache tables (populated by Convex actions):**
- `candlestickCache` — OHLCV data fetched on-demand from Kalshi API, cached 60s

**App-owned tables:**
- `users` — preferences (categories, platforms, notification toggles)
- `alerts` — user notifications (anomaly, price_change, new_market types)

## Key API Details

### Kalshi
- **Production:** `https://api.elections.kalshi.com/trade-api/v2`
- **Demo/Sandbox:** `https://demo-api.kalshi.co/trade-api/v2` (default, safe for development)
- **Auth:** RSA-PSS SHA-256 — message is `timestamp_ms + METHOD + path`, three headers: `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP`, `KALSHI-ACCESS-SIGNATURE`
- **Rate limits (Basic tier):** 20 reads/sec, 10 writes/sec — we default to 15 reads/sec for safety
- **Pagination:** Cursor-based (`cursor` param in response), not page-number based
- **WebSocket:** `wss://api.elections.kalshi.com/trade-api/ws/v2`
- **Discovery filters:** `mve_filter=exclude` (skip combo markets), `min_close_ts` (skip near-expiry), 5 pages max (1000 markets/cycle)
- **Data model:** Series → Events → Markets hierarchy. `series_ticker` groups recurring markets (e.g., daily BTC price markets)
- **~3,500+ active non-combo markets**, defined trading hours (most active 9:30 AM–8 PM ET)
- **Field naming (Jan–Mar 2026 migration):** Prices use `_dollars` suffix (FixedPointDollars strings, e.g. `"0.6500"`): `yes_ask_dollars`, `yes_bid_dollars`, `last_price_dollars`. Counts use `_fp` suffix (FixedPointCount strings, e.g. `"10.00"`): `volume_fp`, `open_interest_fp`, `count_fp`. Legacy fields (`yes_ask`, `yes_bid`, `last_price`, `volume`, `open_interest`, `count`, `category`) were removed. See `docs.kalshi.com/changelog`.
- **`"0.0000"` gotcha:** FixedPointDollars strings like `"0.0000"` are truthy in Python but mean "no data." Don't use `or` chains — use explicit `float(val) > 0` checks. See `_calculate_yes_price()` in `kalshi.py`.
- **WebSocket channels:** `ticker` (price updates), `trade` (individual trades), `market_lifecycle_v2` (market + event lifecycle). The v2 channel adds `event_lifecycle` messages for instant new-market detection. Private channels (orderbook_delta, fill) require authenticated WS.
- **Dynamic WS subscriptions:** `update_subscription` command with `action: "add_markets"` / `"delete_markets"` adds/removes tickers without reconnecting. Requires subscription IDs (`sid`) from confirmation messages.
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

Defined in `sql/schema.sql` and inline in store implementations.

**Core tables:** `markets` (with UNIQUE(platform, external_id)), `events` (FK to markets, indexed by market_id, event_type, timestamp). All timestamps are Unix milliseconds (INTEGER).

**Phase 2 tables:** `topic_clusters`, `market_cluster_memberships`, `anomalies`, `anomaly_markets` — see spec Section 7.2.

**PostgreSQL specifics:**
- BIGSERIAL primary keys, `$1/$2/$3` numbered params (not `?`)
- `INSERT ... ON CONFLICT DO UPDATE` for upserts (not `INSERT OR REPLACE`, to preserve ID stability)
- Events table: `PARTITION BY RANGE (timestamp)` with monthly partitions
- 5 materialized views: `v_current_market_state`, `v_active_anomalies`, `v_trending_topics`, `v_market_summaries`, `v_hourly_activity`
- `compute_candlesticks()` aggregates OHLCV from existing `price_change` events via SQL CTEs (no separate candle table)
- Connection pooling via `asyncpg.create_pool()`

## Relationship: Nexus ↔ MarketFinder (Monorepo)

This is a **monorepo** containing both the data pipeline (`nexus/`) and the webapp (`webapp/`). They share the Convex backend (`convex/`) as a single source of truth.

- **Nexus** (`nexus/`): Python data pipeline. Source of truth for all market data. Syncs precomputed data to Convex.
- **MarketFinder** (`webapp/`): React + Convex webapp. Read-only presentation layer. Reads from Convex tables populated by Nexus.
- **Convex** (`convex/`): Shared backend. Schema, mutations, and queries live here — one copy, no duplication.
- **MarketFinder ETL** (`marketfinder_ETL-main/`): **Deprecated.** Reference repo only (gitignored).

## Infrastructure

- **GitHub repo:** `algorhythmic/projectnexus`
- **Supabase:** PostgreSQL host (use direct connection port 5432, NOT PgBouncer 6543)
- **Fly.io:** DEPLOYED and running (`shared-cpu-1x`, 1GB RAM, app `projectnexus`). OOM-prone at 730MB avg RSS — detection capped at 200 markets/cycle. Deploy with `fly deploy` from repo root.
- **Convex (new):** `deafening-starling-749` — fresh dev cloud deployment for Nexus sync. Cloud URL: `https://deafening-starling-749.convex.cloud`. Deploy key set via `fly secrets set CONVEX_DEPLOY_KEY=...`.
- **Convex (legacy):** `sensible-parakeet-564` — old MarketFinder deployment, schema drift from ETL repo overwriting via `npx convex dev`. Crons accumulated 461.9MB in `priceHistory`. Should be paused or deleted — no longer used by Nexus.
- **Containerized auth:** Inline PEM key support via `KALSHI_PRIVATE_KEY_PEM` env var (for Fly.io deployment where key file isn't available)

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
- Poetry not yet installed — install with `pip install poetry` or `pipx install poetry`
- `gh` CLI IS available (`/opt/homebrew/bin/gh`)

## Commands Reference

```bash
# ─── Python (from repo root) ───
python -m poetry install
python -m poetry run pytest tests/ -v
python -m poetry run nexus info          # Show config
python -m poetry run nexus run           # Start polling loop
python -m poetry run nexus discover      # One-shot discovery cycle
python -m poetry run nexus detect        # One-shot detection cycle
python -m poetry run nexus db-stats      # Market/event counts
python -m poetry run nexus refresh-views # Refresh PostgreSQL materialized views
python -m poetry run nexus health        # Show market health scores from trade flow
python -m poetry run nexus backtest      # Replay detection against historical data
python -m poetry run nexus candlesticks TICKER  # Fetch OHLCV for a market
python -m poetry run nexus taxonomy      # Display Kalshi category hierarchy
python -m poetry run nexus exchange-status  # Check exchange operational status

# ─── Convex (from repo root) ───
npm install                              # First time only
npx convex dev --once                    # Deploy schema + functions
npx convex dev                           # Watch mode for development

# ─── Webapp (from webapp/) ───
cd webapp && npm install                 # First time only
npm run dev:frontend                     # Vite dev server
npx vite build                           # Production build
npx tsc --noEmit                         # Type check

# ─── Deploy (always Convex first, then Fly.io) ───
npx convex dev --once                    # 1. Deploy Convex schema + functions
fly deploy                               # 2. Deploy Nexus to Fly.io
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

- **Supabase 500MB limit:** Discovery was accumulating 144K+ markets from cursor instability. Fixed: 5 pages max, mve_filter=exclude, min_close_ts. Stale markets purged but autovacuum may not have reclaimed space yet.
- **Fly.io 1GB RAM:** Detection capped at 200 markets/cycle. `_last_cycle_ts` initialized to 10min ago (not 0) to prevent OOM on restart. Off-peak RSS: ~78MB. Monitor `rss_mb` in fly logs during peak hours (9:30 AM–8 PM ET).
- **Convex read limits:** Only sync markets with events (1000 vs 90K+). Old documents age out via `cleanupStaleMarkets`.
- **Always verify external API responses** before coding against them — docs and existing code may reference stale field names (learned from the Jan 2026 `_dollars` migration).

## Important Warnings

- **Never commit `.env` or `.env.local` files** — they contain API keys and deployment targets.
- **Default to demo mode** (`KALSHI_USE_DEMO=true`) to avoid hitting production rate limits during development.
- **Don't add heavy dependencies** without checking the spec. Nexus is deliberately lean in Phase 1.
- **Don't break existing implementations.** Phases 1–3 are complete — understand existing code before modifying.
- **Deploy Convex before Fly.io** — if Python sends a field Convex doesn't expect, it throws `ConvexError`.
- **Don't write to sync tables** from the webapp — `nexusMarkets`, `activeAnomalies`, `trendingTopics`, `marketSummaries` are Nexus-owned. Only `users` and `alerts` are app-owned.
- **Don't add cron jobs** to `convex/crons.ts` — all data ingestion happens in Nexus on Fly.io.
- **Auth tables** (`authSessions`, `authAccounts`, etc.) are managed by `@convex-dev/auth` — don't modify them directly.
