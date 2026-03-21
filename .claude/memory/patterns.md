# Code Patterns & Conventions

## Architecture
- BaseAdapter ABC → discover() + connect() — all platform adapters implement this
- BaseStore ABC → SQLiteStore (Phase 1), PostgresStore (Phase 2)
- LoggerMixin — all classes inherit for `.logger` property (structlog)
- Settings singleton via `from nexus.core.config import settings`
- Shared Pydantic types in `nexus/core/types.py`

## Pydantic
- Use `field_validator` not deprecated `validator` (Pydantic v2)
- Use `SettingsConfigDict` for BaseSettings

## Async
- All I/O is async (aiosqlite, httpx)
- CLI wraps async with `asyncio.run()`
- Tests: `asyncio_mode = "auto"` in pyproject.toml

## HTTP
- RateLimiter class in adapters/base.py — asyncio-based
- make_request() retries on 5xx/429 with exponential backoff, raises on other 4xx
- Kalshi auth: override `_build_headers()` to inject RSA-PSS signed headers

## Database
- SQLite with WAL mode and foreign keys enabled
- All timestamps are Unix milliseconds (INTEGER)
- Markets have UNIQUE(platform, external_id) for upserts
- Separate SELECT+INSERT/UPDATE for upserts (not INSERT OR REPLACE, to preserve id stability)

## WebSocket
- KalshiAdapter.connect(tickers) → AsyncIterator[EventRecord]
- WS events have market_id=0 with ticker in metadata JSON; IngestionManager resolves to DB IDs
- EventBus: bounded asyncio.Queue + batch drain worker for backpressure
- IngestionManager: TaskGroup orchestrates discovery + streaming concurrently
- Reconnect: exponential backoff from ws_reconnect_delay to ws_reconnect_max_delay
- Channels: ticker → PRICE_CHANGE, trade → TRADE, market_lifecycle → STATUS_CHANGE

## Monitoring (Milestone 1.3)
- MetricsCollector: in-memory, sync methods, rolling throughput window via deque
- ErrorCategory enum: ws_disconnect, ws_error, auth_token_expiry, rate_limit_hit, discovery_error, store_error
- HealthReporter: periodic asyncio.Task logs MetricsSnapshot every N seconds
- Metrics wired into EventBus + IngestionManager via optional parameter
- Store integrity: get_duplicate_event_count, get_event_gaps (LEAD() window fn), get_ordering_violations
- CLI `nexus validate`: runs integrity checks, prints Decision Gate status

## Testing
- `python -m poetry run pytest tests/ -v`
- conftest.py: `tmp_store`, `rsa_key_pair`, `sample_settings` fixtures
- Never hit real APIs in tests — use FakeAdapter/FakeStreamingAdapter pattern
- Bus tests need a real market in DB (FK constraint) — use _insert_market() helper
