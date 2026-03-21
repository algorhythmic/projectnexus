---
name: Kalshi API Deep Dive Feature Inventory
description: Complete inventory of features implemented from the Kalshi API deep dive plan (2026-03-20) — 4 sprints, 10 features, 98 new tests
type: project
---

## Features Implemented (2026-03-20)

**Why:** Competitive analysis revealed Nexus used only 5 of 94 Kalshi REST endpoints and 3 of 11 WS channels. The deep dive synthesizes multiple unused endpoints into features that go beyond what competitors offer.

**How to apply:** These features are live in the codebase but need Convex + Fly.io redeployment to reach production.

### Sprint 1: Infrastructure Wins
- **Feature D**: Dynamic WS subscriptions — `update_subscription` adds tickers without reconnecting
- **Feature B**: Lifecycle v2 — `market_lifecycle_v2` channel enables instant new-market detection
- **Feature E**: Exchange health — `get_exchange_status()` / `get_exchange_schedule()` methods
- **Feature G**: Single market lookup — `get_market(ticker)` for O(1) REST lookup

### Sprint 2: Candlestick Charts
- **Feature C (partial)**: Candlestick charts — Convex caching proxy + lightweight-charts React component
- **Feature F**: Category taxonomy — `get_category_taxonomy()` replaces per-event API calls

### Sprint 3: Market Intelligence
- **Feature A**: Market health score — 5-signal synthesis in `nexus/intelligence/health.py`
  - Signals: trade velocity, orderbook imbalance, whale activity, spread tightness, momentum
  - Weights: 0.25, 0.20, 0.20, 0.15, 0.20
  - In-memory rolling windows, no new DB tables

### Sprint 4: Historical + Phase 5 Prep
- **Feature C (full)**: Candlestick SQL aggregation from existing events table
- **Series detection**: `nexus/correlation/series_detector.py` — coordinated moves across market series
- **Feature H (partial)**: Catalyst attribution — `nexus/intelligence/narrative.py`
  - Infers catalyst_type: whale, news, momentum, pre_resolution
  - Structured CatalystAnalysis dataclass ready for Phase 5 LLM prompts
- **Backtest CLI**: `nexus backtest` replays detection rules against historical data

### New Kalshi REST Methods on KalshiAdapter
- `get_market(ticker)` — single market lookup
- `get_exchange_status()` / `get_exchange_schedule()` — health check
- `get_candlesticks(ticker, period, start, end)` — OHLCV data
- `get_series(series_ticker?)` — series metadata
- `get_category_taxonomy()` — full category hierarchy
- `get_orderbook(ticker)` — bid/ask depth levels
- `get_trades(ticker?, limit, cursor, min_ts, max_ts)` — recent trades
- `get_milestones(event_ticker?)` — resolution tracking

### Deployment Needed
1. `npx convex dev --once` — deploy candlestickCache table + healthScore field + candlesticks action
2. `fly deploy` — deploy Python pipeline with health tracker + series detector + new REST methods
