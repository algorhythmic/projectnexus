# CLAUDE.md — Project Nexus

## What Is This Project

Nexus is a **real-time prediction market intelligence engine**. It ingests streaming data from prediction market platforms (Kalshi, Polymarket), detects anomalous price/volume movements, identifies correlated shifts across semantically related markets, and surfaces structured alerts.

The full specification is in `projectnexus_specdoc.md` at the repo root. Always consult it for architectural decisions, API details, and phase definitions.

## Current Status

**Phase 1, Milestone 1.1 (Project Scaffolding) — COMPLETE**

What exists:
- Kalshi REST adapter with RSA-PSS SHA-256 authentication
- SQLite event store (markets + events tables, WAL mode)
- Market discovery polling loop with price change detection
- CLI (`nexus info`, `nexus db-init`, `nexus db-stats`, `nexus discover`, `nexus run`)
- 35 passing tests

**Completed milestones:**
- Phase 1: Kalshi adapter, WebSocket streaming, stability monitoring (Milestones 1.1–1.3)
- Phase 2: Anomaly detection, topic clustering, cluster correlation (Milestones 2.1–2.3)
- Phase 3: Polymarket adapter, PostgreSQL migration, cross-platform correlation (Milestones 3.1–3.3)
- Phase 4, Milestone 4.1: Convex sync layer (PostgreSQL → Convex)

**Next milestones:**
- Phase 4, Milestone 4.2: Webapp updates (MarketFinder integration)
- Phase 5: LLM narrative layer

## Repository Layout

```
projectnexus/                   # Git root
├── nexus/                      # Python package
│   ├── core/                   # config.py, logging.py, types.py
│   ├── adapters/               # auth.py, base.py, kalshi.py, polymarket.py (stub)
│   ├── ingestion/              # discovery.py, bus.py (stub)
│   ├── store/                  # base.py, sqlite.py, postgres.py
│   ├── correlation/            # detector, correlator, cross_platform
│   ├── sync/                   # convex_client.py, sync.py
│   └── cli.py
├── sql/                        # schema.sql, migrations/, views/
├── tests/                      # pytest suite
├── projectnexus_specdoc.md     # Master specification
├── pyproject.toml              # Poetry config
└── CLAUDE.md                   # This file
```

The `marketfinder-main/` and `marketfinder_ETL-main/` directories are gitignored reference repos used during porting. They are NOT part of the Nexus codebase.

## Tech Stack

- **Python 3.11+** (currently running 3.13 on this machine)
- **Poetry** for dependency management (`python -m poetry` — not on PATH directly)
- **aiosqlite** for async SQLite (Phase 1), PostgreSQL planned for Phase 2
- **httpx** for async HTTP
- **websockets** for WebSocket connections (Milestone 1.2)
- **cryptography** for RSA-PSS signing (Kalshi auth)
- **pydantic** + **pydantic-settings** for config and data models
- **structlog** for structured JSON logging
- **typer** + **rich** for CLI
- **pytest** + **pytest-asyncio** for testing

## Code Conventions

### Architecture Patterns
- **BaseAdapter ABC** (`nexus/adapters/base.py`): All platform adapters implement `discover()` (REST polling) and `connect()` (WebSocket streaming). The base class provides `RateLimiter`, `make_request()` with retry/backoff, and httpx client management.
- **BaseStore ABC** (`nexus/store/base.py`): Database abstraction. SQLiteStore is the Phase 1 implementation. PostgresStore is Phase 2.
- **LoggerMixin** (`nexus/core/logging.py`): All classes that need logging inherit from this mixin to get a `.logger` property.
- **Settings singleton** (`nexus/core/config.py`): Pydantic BaseSettings with `.env` file support. Import as `from nexus.core.config import settings`.

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
- Fixtures in `tests/conftest.py`: `tmp_store` (temp SQLite), `rsa_key_pair` (ephemeral RSA keys), `sample_settings`
- Tests do NOT hit real APIs — use mock adapters and temp databases

## Key API Details

### Kalshi
- **Production:** `https://trading-api.kalshi.com/trade-api/v2`
- **Demo/Sandbox:** `https://demo-api.kalshi.com/trade-api/v2` (default, safe for development)
- **Auth:** RSA-PSS SHA-256 — message is `timestamp_ms + METHOD + path`, three headers: `KALSHI-ACCESS-KEY`, `KALSHI-ACCESS-TIMESTAMP`, `KALSHI-ACCESS-SIGNATURE`
- **Rate limits (Basic tier):** 20 reads/sec, 10 writes/sec — we default to 15 reads/sec for safety
- **Pagination:** Cursor-based (`cursor` param in response), not page-number based
- **WebSocket:** `wss://trading-api.kalshi.com/trade-api/ws/v2` (Milestone 1.2)

### Polymarket (Phase 3)
- **CLOB WebSocket:** `wss://ws-subscriptions-clob.polymarket.com`
- **RTDS WebSocket:** `wss://ws-live-data.polymarket.com`
- **Auth:** EIP-712 wallet signatures + HMAC-SHA256 API credentials

## Database Schema

Defined in `sql/schema.sql` and inline in `nexus/store/sqlite.py`.

**Phase 1 tables:** `markets` (with UNIQUE(platform, external_id)), `events` (FK to markets, indexed by market_id, event_type, timestamp). All timestamps are Unix milliseconds (INTEGER).

**Phase 2 adds:** `topic_clusters`, `market_cluster_memberships`, `anomalies`, `anomaly_markets` — see spec Section 7.2.

## Relationship to MarketFinder

Nexus and MarketFinder are **separate systems** connected only by a sync layer (Phase 4). They share no runtime dependencies.

- **MarketFinder** (`marketfinder-main/`): React + Convex webapp. Stays as-is. Becomes a presentation layer.
- **MarketFinder ETL** (`marketfinder_ETL-main/`): Python ETL pipeline. **Deprecated.** Its useful code (extractors, engines, config patterns) has been ported into Nexus.
- **Nexus** is the source of truth for all market data. Convex becomes a read-only sync target in Phase 4.

## Environment Notes

- Windows 11 with Git Bash shell
- Poetry is installed via pip, invoked as `python -m poetry` (not on PATH as bare `poetry`)
- Poetry venvs configured as in-project (`.venv/`) to avoid Windows long-path issues
- Python 3.13 from Microsoft Store — the `pyproject.toml` targets `^3.11`
- `gh` CLI is NOT installed — use git commands directly for repository operations

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
```

## Important Warnings

- **Never commit `.env` files** — they contain API keys. Use `.env.example` as a template.
- **Default to demo mode** (`KALSHI_USE_DEMO=true`) to avoid hitting production rate limits during development.
- **Don't add heavy dependencies** without checking the spec. Nexus is deliberately lean in Phase 1. Dependencies like polars, scikit-learn, airflow, and kafka are Phase 2+ concerns.
- **Stub files are intentional.** Files like `polymarket.py`, `postgres.py`, `bus.py`, `correlation/__init__.py`, and `sync/__init__.py` are placeholders for future phases. Don't implement them prematurely.
