# CLAUDE.md — Project Nexus

## What Is This Project

Nexus is a **real-time prediction market intelligence engine**. It ingests streaming data from prediction market platforms (Kalshi, Polymarket), detects anomalous price/volume movements, identifies correlated shifts across semantically related markets, and surfaces structured alerts.

The full specification is in `projectnexus_specdoc.md` at the repo root. Always consult it for architectural decisions, API details, and phase definitions.

## Current Status

**223 tests passing** (+ 14 PostgreSQL integration tests that skip without `TEST_POSTGRES_DSN`)

**Completed milestones:**
- Phase 1: Kalshi REST adapter, WebSocket streaming, stability monitoring (Milestones 1.1–1.3)
- Phase 2: Anomaly detection, topic clustering, cluster correlation (Milestones 2.1–2.3)
- Phase 3: Polymarket adapter, PostgreSQL migration, cross-platform correlation (Milestones 3.1–3.3)
- Phase 4, Milestone 4.1: Convex sync layer (PostgreSQL → Convex via HTTP API)

**Next milestones:**
- Deploy Nexus to Fly.io
- Phase 4, Milestone 4.2: Webapp updates (MarketFinder integration)
- Phase 5: LLM narrative layer

## Repository Layout

```
projectnexus/                   # Git root
├── nexus/                      # Python package
│   ├── core/                   # config.py, logging.py, types.py
│   ├── adapters/               # auth.py, base.py, kalshi.py, polymarket.py
│   ├── ingestion/              # discovery.py, bus.py
│   ├── store/                  # base.py, sqlite.py, postgres.py, __init__.py (factory)
│   ├── correlation/            # detector, correlator, cross_platform
│   ├── sync/                   # convex_client.py, sync.py
│   └── cli.py
├── sql/                        # schema.sql, migrations/, views/
├── tests/                      # pytest suite
├── Dockerfile                  # Fly.io deployment
├── fly.toml                    # Fly.io config
├── projectnexus_specdoc.md     # Master specification
├── pyproject.toml              # Poetry config
└── CLAUDE.md                   # This file
```

The `marketfinder-main/` and `marketfinder_ETL-main/` directories are gitignored reference repos used during porting. They are NOT part of the Nexus codebase.

## Tech Stack

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

## Code Conventions

### Architecture Patterns
- **BaseAdapter ABC** (`nexus/adapters/base.py`): All platform adapters implement `discover()` (REST polling) and `connect()` (WebSocket streaming). The base class provides `RateLimiter`, `make_request()` with retry/backoff, and httpx client management.
- **BaseStore ABC** (`nexus/store/base.py`): Database abstraction. SQLiteStore (Phase 1) and PostgresStore (Phase 2+) both implement it. Use `create_store(settings)` factory from `nexus/store/__init__.py`.
- **LoggerMixin** (`nexus/core/logging.py`): All classes that need logging inherit from this mixin to get a `.logger` property.
- **Settings singleton** (`nexus/core/config.py`): Pydantic BaseSettings with `.env` file support. Import as `from nexus.core.config import settings`.
- **EventBus** (`nexus/ingestion/bus.py`): Bounded `asyncio.Queue` with batch drain worker for backpressure.
- **IngestionManager** (`nexus/ingestion/discovery.py`): TaskGroup orchestrates discovery + streaming concurrently.
- **MetricsCollector** (`nexus/core/`): In-memory metrics with rolling throughput window. ErrorCategory enum tracks ws_disconnect, rate_limit_hit, etc.

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

## Key API Details

### Kalshi
- **Production:** `https://api.elections.kalshi.com/trade-api/v2`
- **Demo/Sandbox:** `https://demo-api.kalshi.co/trade-api/v2` (default, safe for development)
- **Auth:** RSA-PSS SHA-256 — message is `timestamp_ms + METHOD + path`, three headers: `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP`, `KALSHI-ACCESS-SIGNATURE`
- **Rate limits (Basic tier):** 20 reads/sec, 10 writes/sec — we default to 15 reads/sec for safety
- **Pagination:** Cursor-based (`cursor` param in response), not page-number based
- **WebSocket:** `wss://api.elections.kalshi.com/trade-api/ws/v2`
- **~3,500 markets**, defined trading hours

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
- 4 materialized views: `v_current_market_state`, `v_active_anomalies`, `v_trending_topics`, `v_market_summaries`
- Connection pooling via `asyncpg.create_pool()`

## Relationship to MarketFinder

Nexus and MarketFinder are **separate systems** connected only by a sync layer (Phase 4). They share no runtime dependencies.

- **MarketFinder** (`marketfinder-main/`): React + Convex webapp. Stays as-is. Becomes a presentation layer.
- **MarketFinder ETL** (`marketfinder_ETL-main/`): Python ETL pipeline + duplicate Convex backend. **Deprecated.** Its useful code has been ported into Nexus. Its `convex/` directory was likely the last thing deployed to `sensible-parakeet-564`, causing schema drift with `marketfinder-main/`.
- **Nexus** is the source of truth for all market data. Convex becomes a read-only sync target in Phase 4.

## Infrastructure

- **GitHub repo:** `algorhythmic/projectnexus`
- **Supabase:** PostgreSQL host (use direct connection port 5432, NOT PgBouncer 6543)
- **Fly.io:** Deployment config ready (`Dockerfile` + `fly.toml`), not yet deployed
- **Convex (new):** `deafening-starling-749` — fresh dev cloud deployment for Nexus sync. Cloud URL: `https://deafening-starling-749.convex.cloud`. Deploy key set via `fly secrets set CONVEX_DEPLOY_KEY=...`.
- **Convex (legacy):** `sensible-parakeet-564` — old MarketFinder deployment, schema drift from ETL repo overwriting via `npx convex dev`. Crons accumulated 461.9MB in `priceHistory`. Should be paused or deleted — no longer used by Nexus.
- **Containerized auth:** Inline PEM key support via `KALSHI_PRIVATE_KEY_PEM` env var (for Fly.io deployment where key file isn't available)

## Environment Notes

- Windows 11 with Git Bash shell
- Poetry is installed via pip, invoked as `python -m poetry` (not on PATH as bare `poetry`)
- Poetry venvs configured as in-project (`.venv/`) to avoid Windows long-path issues
- Python 3.13 from Microsoft Store — the `pyproject.toml` targets `^3.11`
- `gh` CLI is NOT installed — use git commands directly for repository operations
- Git identity: `algorhythmic` / `algorhythmic@users.noreply.github.com`

## Commands Reference

```bash
# Install dependencies
python -m poetry install

# Run tests
python -m poetry run pytest tests/ -v

# CLI
python -m poetry run nexus info          # Show config
python -m poetry run nexus db-init       # Create SQLite tables
python -m poetry run nexus db-stats      # Market/event counts
python -m poetry run nexus discover      # One-shot discovery cycle
python -m poetry run nexus run           # Start polling loop
python -m poetry run nexus validate      # Run store integrity checks (Decision Gate status)
python -m poetry run nexus db-migrate    # SQLite → PostgreSQL backfill
python -m poetry run nexus refresh-views # Refresh PostgreSQL materialized views
```

## Important Warnings

- **Never commit `.env` files** — they contain API keys. Use `.env.example` as a template.
- **Default to demo mode** (`KALSHI_USE_DEMO=true`) to avoid hitting production rate limits during development.
- **Don't add heavy dependencies** without checking the spec. Nexus is deliberately lean in Phase 1. Dependencies like polars, scikit-learn, airflow, and kafka are Phase 2+ concerns.
- **Don't break existing implementations.** Phases 1–3 are complete — polymarket.py, postgres.py, bus.py, correlation/, and sync/ are all implemented. Understand existing code before modifying.
