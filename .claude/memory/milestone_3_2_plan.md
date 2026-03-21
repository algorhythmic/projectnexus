# Milestone 3.2: PostgreSQL Migration Plan

## Status: IMPLEMENTED (2026-03-09)

## Context
- Milestone 3.1 complete (Polymarket adapter, 187 tests passing)
- Next: Migrate storage from SQLite to PostgreSQL
- User chose: asyncpg driver, skip PG tests when no database

## Implementation Steps

### Step 1: Add asyncpg dependency
- `pyproject.toml`: add `asyncpg = "^0.30.0"`

### Step 2: Config additions (`nexus/core/config.py`)
```python
store_backend: str = "sqlite"  # "sqlite" or "postgres"
postgres_dsn: str = ""
postgres_pool_min: int = 2
postgres_pool_max: int = 10
```

### Step 3: Implement PostgresStore (`nexus/store/postgres.py`)
- Replace stub with full implementation (~450 lines)
- All 24 BaseStore abstract methods using asyncpg
- Key SQL differences: BIGSERIAL, $1 params, ON CONFLICT DO UPDATE, RETURNING id, JSONB
- Events table: PARTITION BY RANGE (timestamp), monthly partitions
- 4 materialized views: v_current_market_state, v_active_anomalies, v_trending_topics, v_market_summaries
- Connection pooling via asyncpg.create_pool()

### Step 4: Store factory (`nexus/store/__init__.py`)
- `create_store(settings) -> BaseStore` function
- Lazy import of PostgresStore (asyncpg not required for SQLite mode)

### Step 5: CLI updates (`nexus/cli.py`)
- Replace SQLiteStore() with create_store(settings) everywhere
- Add `db-migrate` command (SQLite→PG backfill)
- Add `refresh-views` command
- Update `info` to show PG config

### Step 6: Tests (`tests/test_postgres.py`)
- ~15 integration tests with @pytest.mark.postgres
- Skip when TEST_POSTGRES_DSN not set
- pg_store fixture in conftest.py with table truncation

### Step 7: Update conftest.py
- Add pg_store fixture
- Register postgres marker in pyproject.toml

## Files to Modify/Create
| File | Action |
|------|--------|
| `pyproject.toml` | Modify — add asyncpg, pytest marker |
| `nexus/core/config.py` | Modify — add 4 PG settings |
| `nexus/store/postgres.py` | Replace stub — full PostgresStore |
| `nexus/store/__init__.py` | Modify — add create_store() factory |
| `nexus/cli.py` | Modify — use factory, add commands |
| `tests/conftest.py` | Modify — add pg_store fixture |
| `tests/test_postgres.py` | Create — ~15 integration tests |

## Key Technical Notes
- asyncpg Record objects support both index and key access
- SQLite `?` → asyncpg `$1, $2, $3` numbered params
- SQLite `INSERT OR REPLACE` → PG `INSERT ... ON CONFLICT DO UPDATE`
- SQLite `cursor.lastrowid` → PG `RETURNING id`
- SQLite `executescript()` → PG `execute()` with multi-statement
- Materialized views refreshed via `REFRESH MATERIALIZED VIEW CONCURRENTLY`
