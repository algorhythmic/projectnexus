# Project Nexus — Persistent Memory

## Project Identity
- Real-time prediction market intelligence engine
- Repo: https://github.com/algorhythmic/projectnexus.git
- Root: C:\workspace\code\projectnexus
- Full spec: `projectnexus_specdoc.md` at repo root
- CLAUDE.md at repo root has comprehensive project directives

## Current State (as of 2026-03-20)
- **MONOREPO** — MarketFinder merged into projectnexus under `webapp/`, Convex at root `convex/`
- Phases 1–4 COMPLETE (ingestion, detection, multi-platform, PG, sync, webapp)
- **Kalshi API deep dive COMPLETE** — 4 sprints implemented (Features A-G + Phase 5 prep)
- 324 tests passing (+ 14 PG integration tests that skip without TEST_POSTGRES_DSN)
- Git identity: algorhythmic / algorhythmic@users.noreply.github.com
- Fly.io deployment LIVE with production tuning
- Next: deploy Convex schema (`npx convex dev --once`), deploy Fly.io (`fly deploy`), Phase 5 (LLM narrative)

## Kalshi API Deep Dive (completed 2026-03-20)
- See [kalshi-api-features.md](kalshi-api-features.md) for feature inventory
- Sprint 1: Dynamic WS subscriptions, lifecycle v2, exchange health, market lookup
- Sprint 2: Candlestick charts (lightweight-charts + Convex caching proxy), category taxonomy
- Sprint 3: Market intelligence health score (5-signal synthesis: velocity, imbalance, whale, spread, momentum)
- Sprint 4: Series pattern detection, candlestick SQL aggregation, catalyst attribution, backtest CLI
- New modules: `nexus/intelligence/` (health + narrative), `nexus/correlation/series_detector.py`
- New Convex module: `convex/candlesticks.ts` (caching proxy action)
- New React components: `CandlestickChart.tsx`, `MarketDetailDialog.tsx`
- New CLI commands: candlesticks, taxonomy, exchange-status, health, backtest
- 98 new tests added (226 → 324)

## Infrastructure (as of 2026-03-18)
- **Supabase**: Stale markets purged, awaiting autovacuum to reclaim space (was 0.68 GB). See [infrastructure-issues.md](infrastructure-issues.md)
- **Fly.io**: DEPLOYED (`shared-cpu-1x`, 1GB RAM, app `projectnexus`). RSS monitoring live — off-peak baseline ~78 MB
- **Convex (active)**: `deafening-starling-749` — receiving sync, read limit warnings should resolve after purge
- **Convex (legacy)**: `sensible-parakeet-564` — should be paused/deleted

## Anomaly Detection
- See [anomaly-tuning.md](anomaly-tuning.md) for threshold calibration
- Severity now uses logarithmic scaling (commit 611ec56)
- Anomaly summaries include market title + price from/to
- Deduplication: markets with active anomalies are skipped

## Discovery & Sync (as of 2026-03-19)
- Kalshi discovery limited to 5 pages (1000 markets), was 30 (6000)
- mve_filter=exclude skips combo markets (garbled titles)
- min_close_ts skips markets expiring <1 hour
- Only markets with events synced to Convex (now ~1000 vs 90K+)
- First cycle emits `price_change` events via `_seed_with_events()` (was silent cache seed)
- First-seen markets emit both `new_market` + `price_change` (materialized view needs `price_change`)
- Convex stale cleanup: `cleanupStaleMarkets` mutation in convex/nexusSync.ts, throttled 5 min
- Convex deploy command: `npx convex dev --once` from repo root (NOT `npx convex deploy` — that targets prod)
- Materialized view `v_current_market_state` refreshes on dedicated 5-min timer (was broken — shared timer with summaries)
- Categories enriched from Kalshi events API (`_event_category_cache`), cached per process lifetime
- Event titles stored in market description for group display in MarketFinder

## Environment
- Windows 11, Git Bash shell
- Python 3.13 (Microsoft Store), target ^3.11
- Poetry invoked as `python -m poetry` (not on PATH directly)
- Poetry venvs are in-project (.venv/) to avoid Windows long-path issues
- `gh` CLI not installed — use git directly
- Reference repos (gitignored): `marketfinder-main/`, `marketfinder_ETL-main/`
- MarketFinder old repo (`C:\Workspace\Code\marketfinder`) — archived, merged into monorepo
- Convex runs from repo root (`npx convex dev --once`), webapp from `webapp/` (`npm run dev:frontend`)

## Key Patterns
- See [patterns.md](patterns.md) for code conventions
- See [api-details.md](api-details.md) for platform API reference

## External APIs
- [kalshi_api_reference.md](kalshi_api_reference.md) — Kalshi REST + WebSocket field names, types, and deprecation status (verified 2026-03-19)
- [project_kalshi_api_migration.md](project_kalshi_api_migration.md) — Context on the Jan–Mar 2026 field migration and the string "0.0000" gotcha

## Feedback
- [feedback_verify_external_apis.md](feedback_verify_external_apis.md) — Always verify live API response shapes before coding against them
