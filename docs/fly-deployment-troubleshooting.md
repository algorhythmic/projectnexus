# Fly.io Deployment — Troubleshooting Reference

Errors encountered during the initial Nexus deployment to Fly.io (March 2026), with root causes and fixes.

---

## 1. ENTRYPOINT Doubling

**Symptom:** Container ran `nexus nexus run --platform all` — command doubled.

**Cause:** Dockerfile had `ENTRYPOINT ["nexus"]` and fly.toml's process command also started with `nexus run`. Fly concatenates the ENTRYPOINT with the process command.

**Fix:** Remove `ENTRYPOINT` from Dockerfile. Use `CMD ["python", "-m", "nexus.cli", "run"]` as the default, and let fly.toml provide the full command via `[processes]`.

```toml
# fly.toml
[processes]
  worker = 'python -m nexus.cli run --platform all'
```

```dockerfile
# Dockerfile — no ENTRYPOINT
CMD ["python", "-m", "nexus.cli", "run"]
```

---

## 2. CLI Entry Point Not Found in Production Docker Stage

**Symptom:** `nexus: command not found` in the production stage of a multi-stage Docker build.

**Cause:** Poetry with `virtualenvs.create false` needs the project source present during `poetry install` to generate the `nexus` console script entry point. The builder stage only had `pyproject.toml` and `poetry.lock`.

**Fix:** Copy `nexus/` and `sql/` into the builder stage *before* `poetry install`, then copy `/usr/local/bin/` (which contains the entry point) to the production stage.

```dockerfile
FROM python:3.11-slim AS builder
WORKDIR /app
COPY pyproject.toml poetry.lock ./
COPY nexus/ nexus/
COPY sql/ sql/
RUN poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --without dev -E postgres

FROM python:3.11-slim AS production
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY nexus/ nexus/
COPY sql/ sql/
```

---

## 3. Typer / Click 8.3 Incompatibility

**Symptom:** `TypeError: Secondary flag is not valid for non-boolean flag` on startup.

**Cause:** Click 8.3 changed how `typer.Option()` handles positional defaults. Pinning `click<8.3` triggered a second error (`make_metavar() missing ctx`) due to Typer 0.9 being incompatible with Python 3.13.

**Fix:** Upgrade `typer` from `^0.9.0` to `>=0.12.0`. Add explicit flag names to all `typer.Option` calls.

```python
# Before (broken with Click 8.3)
platform: str = typer.Option("all", help="Platform: kalshi, polymarket, or all")

# After
platform: str = typer.Option("all", "--platform", help="Platform: kalshi, polymarket, or all")
```

---

## 4. Secrets Leaked in Rich Tracebacks

**Symptom:** Full `Settings` object (API keys, PEM key, Postgres DSN, Convex deploy key) dumped to Fly logs in a Rich traceback.

**Cause:** An unhandled exception (the Typer crash from error #3) triggered Rich's verbose traceback, which printed all local variables including the `Settings` singleton. pydantic's default `__repr__` shows all field values.

**Fix:** Override `__repr__` on the `Settings` class to redact sensitive fields.

```python
_SECRET_FIELDS = frozenset({
    "kalshi_api_key", "kalshi_private_key_pem", "kalshi_private_key_path",
    "postgres_dsn", "convex_deploy_key", "anthropic_api_key",
})

def __repr__(self) -> str:
    fields = []
    for name in self.model_fields:
        value = getattr(self, name)
        if name in self._SECRET_FIELDS and value:
            fields.append(f"{name}='***'")
        else:
            fields.append(f"{name}={value!r}")
    return f"Settings({', '.join(fields)})"

__str__ = __repr__
```

**Post-fix action:** Rotate ALL leaked credentials immediately.

---

## 5. PermissionError on `logs/` Directory

**Symptom:** `PermissionError: [Errno 13] Permission denied: 'logs'` on startup.

**Cause:** The non-root `nexus` user in the Docker container couldn't create `logs/` in `/app`. The logging module tried to create it unconditionally at import time.

**Fix:** Wrap log directory creation in `try/except PermissionError`, falling back to stdout-only logging.

```python
else:
    try:
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)
        root.addHandler(logging.FileHandler(logs_dir / "nexus.log"))
    except PermissionError:
        pass
    root.addHandler(logging.StreamHandler(sys.stdout))
```

---

## 6. PostgreSQL DSN Parsing Error

**Symptom:** Connection string with brackets in the password was interpreted as an IPv6 address.

**Cause:** Special characters (`[`, `]`) in the Supabase-generated password weren't URL-encoded.

**Fix:** URL-encode special characters in the password portion of the DSN when setting Fly secrets.

```bash
# Encode [ as %5B, ] as %5D, etc.
fly secrets set POSTGRES_DSN='postgresql://user:p%5Bass%5Dword@host:5432/db?sslmode=require'
```

---

## 7. Demo API DNS Resolution Failure

**Symptom:** `demo-api.kalshi.com` couldn't be resolved from within the Fly.io network.

**Cause:** `KALSHI_USE_DEMO` defaulted to `true`, pointing at the demo domain which wasn't reachable from the deployment region.

**Fix:** Set `KALSHI_USE_DEMO=false` in fly.toml env vars (or via `fly secrets set`) to use the production API.

---

## 8. Kalshi 401 — Auth Signing Path Missing Prefix

**Symptom:** Every request to Kalshi returned `401 Unauthorized`.

**Cause:** The auth signature was computed over `/markets` but Kalshi requires the full path `/trade-api/v2/markets`. The `BaseAdapter.make_request()` strips the base URL path before passing it to `_build_headers()`.

**Fix:** In `KalshiAdapter.__init__`, extract the URL path prefix from the base URL. In `_build_headers`, prepend it before signing.

```python
# __init__
from urllib.parse import urlparse
self._url_path_prefix = urlparse(base_url).path.rstrip("/")

# _build_headers
sign_path = f"{self._url_path_prefix}{path}"  # e.g. "/trade-api/v2/markets"
```

---

## 9. Kalshi 401 — API Domain Migration

**Symptom:** 401 persisted after fixing the signing path. Response body revealed: *"API has been moved to https://api.elections.kalshi.com/"*.

**Cause:** Kalshi migrated their API from `trading-api.kalshi.com` to `api.elections.kalshi.com`. The old domain returns 401 for all requests with no further detail unless you inspect the response body.

**Fix:** Update all default URLs in `config.py`:

| Endpoint | Old | New |
|----------|-----|-----|
| Production REST | `https://trading-api.kalshi.com/trade-api/v2` | `https://api.elections.kalshi.com/trade-api/v2` |
| Production WS | `wss://trading-api.kalshi.com/trade-api/ws/v2` | `wss://api.elections.kalshi.com/trade-api/ws/v2` |
| Demo REST | `https://demo-api.kalshi.com/trade-api/v2` | `https://demo-api.kalshi.co/trade-api/v2` |
| Demo WS | `wss://demo-api.kalshi.com/trade-api/ws/v2` | `wss://demo-api.kalshi.co/trade-api/ws/v2` |

**Lesson:** Always log response bodies on 401/403 errors — the body often contains the actual reason.

---

## 10. OOM Kill (Out of Memory)

**Symptom:** `Out of memory: Killed process 647 (python)` — kernel OOM killer terminated the process.

**Cause:** Kalshi has 10,000+ open markets. Paginating all of them into a single `List[DiscoveredMarket]` with full `raw_data` dictionaries exceeded the 512MB VM limit.

**Fix (two-pronged):**
1. Add `kalshi_discovery_max_pages` config setting (default 10 = ~2,000 markets) to cap pagination.
2. Bump VM memory from 512MB to 1GB in `fly.toml`.

```toml
[[vm]]
  memory = '1024mb'
```

---

## 11. Database Upsert Hanging Indefinitely

**Symptom:** `"Discovery cycle complete"` log never appeared after discovering 5,000 markets. The pipeline stalled with no errors.

**Cause:** `upsert_markets()` executed 5,000 individual `INSERT ... ON CONFLICT` statements sequentially over a remote Supabase connection. Each round-trip ~100ms, so total time was 8+ minutes — effectively hanging the entire pipeline. Additionally, first-cycle event generation triggered 5,000 more `get_market_by_external_id()` queries.

**Fix:**
1. Replace row-by-row inserts with `unnest`-based batch INSERT (1 query per 500 markets).
2. Skip event generation on first discovery cycle (empty price cache); seed the cache directly.

```python
# Batch upsert via unnest — single round-trip per 500 markets
sql = """
    INSERT INTO markets (platform, external_id, title, description, category,
                         is_active, first_seen_at, last_updated_at)
    SELECT * FROM unnest($1::text[], $2::text[], $3::text[], $4::text[],
                         $5::text[], $6::bool[], $7::bigint[], $8::bigint[])
    ON CONFLICT (platform, external_id) DO UPDATE SET ...
    RETURNING CASE WHEN xmax = 0 THEN 1 ELSE 0 END
"""
rows = await conn.fetch(sql, platforms, external_ids, titles, ...)
```

**Result:** 2,000 markets upserted in ~1 second (down from 8+ minutes).

---

## 12. Stuck Machines After Crash Loops

**Symptom:** Fly machines hit max restart count (10) and stayed in `stopped` state. New deploys updated the image but the machine wouldn't start.

**Cause:** Fly.io stops restarting a machine after 10 consecutive failures. The machine remains allocated but inert.

**Fix:** Destroy the stuck machine and redeploy to create a fresh one.

```bash
fly machines list --app projectnexus
fly machines destroy <machine-id> --force --app projectnexus
fly deploy --app projectnexus
```

---

## General Lessons

1. **Always log response bodies on auth failures.** A 401 might contain a migration notice, rate limit message, or specific error reason that the status code alone doesn't convey.

2. **Redact secrets in `__repr__`.** Any class holding credentials should override `__repr__`/`__str__` to prevent leakage in tracebacks, especially when using Rich or similar verbose formatters.

3. **Test container builds locally before deploying.** Run `docker build --target production .` and `docker run` locally to catch permission errors, missing binaries, and entry point issues before they hit remote logs.

4. **Batch database operations over remote connections.** Individual queries that are fast locally (1ms each) become painfully slow over the internet (100ms+ each). Use `unnest`, `COPY`, or `executemany` for bulk operations.

5. **Cap unbounded pagination.** APIs with thousands of results can OOM a small VM. Always have a configurable page/item limit.

6. **Pin to the specific Fly CLI path on Windows.** The Fly CLI installs to `~/.fly/bin/fly.exe` and may not be on PATH. Use the full path: `/c/Users/<user>/.fly/bin/fly.exe`.
