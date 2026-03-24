# Kalshi API Integration Plan — Unused Endpoints & Use Cases

> Companion to `kalshi-api-reference.md`
> Created: 2026-03-20
> Status: Sprints 1–4 COMPLETE (2026-03-20). See `docs/phase-5-implementation-plan.md` for next steps.

## Current Coverage

**5 of 94 REST endpoints used. 3 of 11 WebSocket channels subscribed.**

| Used | Endpoint | Purpose |
|------|----------|---------|
| REST | `GET /markets` | Market discovery |
| REST | `GET /events/{ticker}` | Category/title enrichment |
| WS | `ticker` | Real-time price/volume |
| WS | `trade` | Trade executions |
| WS | `market_lifecycle` (v1) | Status changes |

---

## Use Cases — Ordered by Value

### Use Case 1: Candlestick Charts in MarketFinder

**Endpoints:** `GET /series/{series}/markets/{ticker}/candlesticks`, `GET /markets/candlesticks` (batch)

**Value:** Currently MarketFinder shows only the last price. Candlestick data enables price history visualization — users can see how a market's probability has moved over time, identify trends, and understand context for anomalies.

**What the API provides:**
- OHLCV data at 1-minute, 1-hour, or 1-day intervals
- Configurable time range via `start_ts` / `end_ts`
- Batch endpoint for multiple markets in one call
- Historical candlesticks available via `/historical/markets/{ticker}/candlesticks`

**Implementation plan:**
1. **Convex action** — create a Convex action (not query) that proxies candlestick requests to Kalshi API on demand (no need to store in DB)
2. **React component** — lightweight chart component (e.g., `lightweight-charts` library) in the market detail/expansion view
3. **Caching** — cache candlestick responses in Convex for 60 seconds to avoid redundant API calls
4. **UI integration** — add a "Price History" section to the expanded market row or detail popover

**Files to modify:**
- `convex/actions.ts` (new) — Kalshi API proxy action
- `webapp/src/components/MarketPriceChart.tsx` (new) — chart component
- `webapp/src/components/markettablecolumns.tsx` — add chart to expanded child rows
- `webapp/package.json` — add chart library dependency

**Estimated effort:** Medium
**Dependencies:** None
**Rate limit impact:** 1 read per chart view (cached 60s)

---

### Use Case 2: Trade Flow & Whale Detection

**Endpoints:** `GET /markets/trades`, `WS orderbook_delta`

**Value:** Large trades and unusual order patterns are leading indicators for price moves. Detecting "whale" activity (large single trades) and order flow imbalances (more buy pressure vs sell) before they move the price gives early anomaly signals.

**What the API provides:**
- `GET /markets/trades` — historical trade log with `trade_id`, `count_fp` (size), `yes_price_dollars`, `taker_side`, `created_time`
- `WS orderbook_delta` — real-time orderbook changes: snapshots + incremental updates showing orders being placed/pulled
- Both include size information to detect outsized trades

**Implementation plan:**
1. **Trade ingestion** — periodically fetch recent trades via REST (every 60s), store in a new `trades` PostgreSQL table
2. **Whale detection** — flag trades where `count_fp` exceeds N standard deviations above the market's average trade size
3. **Order flow imbalance** — subscribe to `orderbook_delta` for top 200 markets, compute buy/sell pressure ratio
4. **New anomaly type** — `trade_flow` anomaly when whale trade or extreme order imbalance detected
5. **Sync to Convex** — whale alerts appear in the anomaly feed

**Files to modify:**
- `nexus/adapters/kalshi.py` — add `fetch_trades()` method, subscribe to `orderbook_delta`
- `sql/schema.sql` — add `trades` table
- `nexus/store/postgres.py` — add trade storage methods
- `nexus/correlation/detector.py` — add trade flow anomaly detection
- `nexus/ingestion/discovery.py` — call trade fetch in discovery loop

**Estimated effort:** Large
**Dependencies:** None
**Rate limit impact:** ~1 read/min for trade polling; WS `orderbook_delta` is free but adds subscription load

---

### Use Case 3: Instant New Market Alerts via `market_lifecycle_v2`

**Endpoints:** `WS market_lifecycle_v2` (replaces our current `market_lifecycle` v1)

**Value:** Currently we discover new markets via 60-second REST polling. The `v2` lifecycle channel includes `event_lifecycle` messages that fire instantly when Kalshi creates new events. This means near-zero latency for new market detection.

**What the API provides:**
- `event_lifecycle` messages — fired when new events are created on the platform
- Enhanced `market_lifecycle_v2` events: `created`, `activated`, `deactivated`, `close_date_updated`, `determined`, `settled`, `fractional_trading_updated`, `price_level_structure_updated`
- `additional_metadata` field with name, title, rules, event_ticker, strike info
- Global channel (no per-market filtering needed — receives ALL lifecycle events)

**Implementation plan:**
1. **Upgrade subscription** — change `market_lifecycle` to `market_lifecycle_v2` in the WS subscribe call
2. **Handle `event_lifecycle`** — when a new event is created, immediately trigger a targeted discovery for that event's markets
3. **Handle enhanced events** — `close_date_updated` for detecting expiry changes, `created` for instant new market awareness
4. **Emit new_market events** — immediately emit `EventType.NEW_MARKET` events without waiting for the next discovery cycle

**Files to modify:**
- `nexus/adapters/kalshi.py` — change channel name, add `event_lifecycle` handler in `_normalize_lifecycle()`
- `nexus/ingestion/manager.py` — handle new event creation → trigger targeted discovery

**Estimated effort:** Small
**Dependencies:** None
**Rate limit impact:** Zero — WebSocket channels are free

---

### Use Case 4: Event-Level Discovery

**Endpoints:** `GET /events` (with `with_nested_markets=true`), `GET /events/{ticker}/metadata`

**Value:** Currently we discover markets first, then enrich with event data. Flipping this — discover events first, then fetch their markets — is more efficient and provides richer metadata (categories, rules, settlement sources). The `with_nested_markets` flag returns all child markets in one call, eliminating the need for separate market pagination.

**What the API provides:**
- `GET /events` — paginated event listing with category, title, status, milestones
- `with_nested_markets=true` — includes all child markets in the response
- `GET /events/{ticker}/metadata` — settlement sources, rules, resolution criteria
- `with_milestones=true` — includes milestone data (sports scores, data releases)

**Implementation plan:**
1. **Event-first discovery** — new discovery mode: paginate events, then extract nested markets
2. **Richer metadata** — store event-level metadata (rules, settlement sources) in a new `event_metadata` column
3. **Better categorization** — use event category directly (already partially implemented via `_enrich_categories`)
4. **Milestone integration** — link markets to milestones for live resolution data

**Files to modify:**
- `nexus/adapters/kalshi.py` — add `discover_events()` method alongside existing `discover()`
- `nexus/ingestion/discovery.py` — option to use event-first discovery
- `nexus/store/postgres.py` — potential schema additions for event metadata

**Estimated effort:** Medium
**Dependencies:** None
**Rate limit impact:** Potentially fewer API calls (one event call returns multiple markets)

---

### Use Case 5: Orderbook Depth Analysis

**Endpoints:** `GET /markets/{ticker}/orderbook`, `WS orderbook_delta`

**Value:** Thin orderbooks signal potential for large price moves — a market with $50 of liquidity at the best bid can move 10% on a single trade. Monitoring orderbook depth provides a leading indicator for anomaly detection: thinning liquidity → higher probability of upcoming price spike.

**What the API provides:**
- `GET /markets/{ticker}/orderbook` — full orderbook snapshot with bid levels
- Asks are derived from reciprocal (NO bids = YES asks)
- `depth` parameter to limit levels returned
- `WS orderbook_delta` — real-time incremental updates

**Implementation plan:**
1. **Periodic snapshots** — fetch orderbook for top N markets by rank score every 5 minutes
2. **Liquidity metric** — compute total $ within 5% of current price (depth score)
3. **Thin book alerts** — flag markets where liquidity drops below threshold
4. **Integration with anomaly detection** — low liquidity + recent price activity = high probability of imminent move

**Files to modify:**
- `nexus/adapters/kalshi.py` — add `fetch_orderbook()` method
- `nexus/correlation/detector.py` — add liquidity-based anomaly scoring
- `nexus/store/postgres.py` — new `orderbook_snapshots` table or in-memory cache

**Estimated effort:** Medium
**Dependencies:** Use Case 2 (shares `orderbook_delta` subscription)
**Rate limit impact:** ~40 reads/5min for top 200 markets (well within limits)

---

### Use Case 6: Exchange Health Monitoring

**Endpoints:** `GET /exchange/status`, `GET /exchange/schedule`, `GET /exchange/announcements`

**Value:** The pipeline currently can't distinguish between "the exchange is down" and "markets are inactive." During exchange maintenance or outside trading hours, the pipeline may generate false staleness alerts or waste resources polling. Exchange status monitoring prevents this.

**What the API provides:**
- `GET /exchange/status` — boolean trading active/inactive + maintenance windows
- `GET /exchange/schedule` — structured trading hours (when markets open/close)
- `GET /exchange/announcements` — platform-wide notices (rule changes, new market types, outages)

**Implementation plan:**
1. **Startup check** — query exchange status on pipeline startup
2. **Periodic poll** — check status every 5 minutes
3. **Schedule awareness** — skip detection cycles during known closed hours
4. **Announcement logging** — log exchange announcements for context on anomalies
5. **Health reporter integration** — include exchange status in pipeline health logs

**Files to modify:**
- `nexus/adapters/kalshi.py` — add `get_exchange_status()` method
- `nexus/ingestion/manager.py` — check status before discovery/detection cycles
- `nexus/core/config.py` — configurable schedule-aware detection

**Estimated effort:** Small
**Dependencies:** None
**Rate limit impact:** ~1 read/5min (negligible)

---

### Use Case 7: Historical Backtesting Data

**Endpoints:** `GET /historical/markets`, `GET /historical/trades`, `GET /historical/markets/{ticker}/candlesticks`, `GET /historical/cutoff`

**Value:** Validate anomaly detection algorithms against historical data. Currently, signal quality is evaluated only on live data. Historical backtesting enables: threshold tuning, new algorithm validation, signal-to-noise ratio measurement (required for Phase 2 Decision Gate).

**What the API provides:**
- Full historical market metadata (settled markets)
- Historical trade data with timestamps and sizes
- Historical candlestick OHLCV data
- Cutoff timestamp to know where live data ends and historical begins

**Implementation plan:**
1. **Backfill script** — CLI command `nexus backfill` to import historical data for a time range
2. **Historical store** — store in same PostgreSQL tables with a `source` flag (live vs historical)
3. **Replay mode** — detection engine can process historical events to simulate real-time detection
4. **Signal validation** — compare detected anomalies against known catalysts from news archives

**Files to modify:**
- `nexus/cli.py` — add `backfill` command
- `nexus/adapters/kalshi.py` — add `fetch_historical_markets()`, `fetch_historical_trades()`
- `nexus/correlation/backtester.py` (new) — replay engine

**Estimated effort:** Large
**Dependencies:** None (but most valuable after Use Cases 1-3 are in place)
**Rate limit impact:** One-time bulk import (can be throttled to stay within limits)

---

### Use Case 8: WebSocket Subscription Optimization

**Endpoints:** WS `update_subscription` command

**Value:** Currently, when new tickers are discovered, the pipeline **disconnects and reconnects** the entire WebSocket to resubscribe with the updated ticker list. The `update_subscription` command allows adding/removing tickers from an existing subscription without dropping the connection — zero downtime, no missed events.

**What the API provides:**
- `update_subscription` command with `action: "add_markets"` or `"delete_markets"`
- Takes `sid` (subscription ID from the original subscribe ack) and `market_tickers`
- Optional `send_initial_snapshot` for newly added markets

**Implementation plan:**
1. **Track subscription IDs** — store the `sid` returned from subscribe acknowledgments
2. **Incremental updates** — when discovery finds new tickers, send `update_subscription` with `add_markets` instead of reconnecting
3. **Market removal** — when markets are deactivated, send `update_subscription` with `delete_markets`
4. **Remove reconnect logic** — eliminate the `_resubscribe_needed` event and reconnection path

**Files to modify:**
- `nexus/adapters/kalshi.py` — store subscription IDs, implement `update_subscription` command
- `nexus/ingestion/manager.py` — replace reconnect-based resubscribe with incremental updates

**Estimated effort:** Small
**Dependencies:** None
**Rate limit impact:** Zero — WebSocket commands are free

---

## Priority Matrix

| Use Case | Value | Effort | Priority |
|----------|-------|--------|----------|
| 3. Instant New Market Alerts (lifecycle v2) | High | Small | **P0** |
| 8. WebSocket Subscription Optimization | Medium | Small | **P0** |
| 6. Exchange Health Monitoring | Medium | Small | **P1** |
| 1. Candlestick Charts | High | Medium | **P1** |
| 4. Event-Level Discovery | Medium | Medium | **P2** |
| 5. Orderbook Depth Analysis | High | Medium | **P2** |
| 2. Trade Flow & Whale Detection | High | Large | **P3** |
| 7. Historical Backtesting | Medium | Large | **P3** |

---

## Implementation Phases

### Phase A — Quick Wins (P0, ~1-2 days)
- Use Case 3: Upgrade `market_lifecycle` → `market_lifecycle_v2`
- Use Case 8: Replace WS reconnect with `update_subscription`

### Phase B — Enrichment (P1, ~3-5 days)
- Use Case 6: Exchange health monitoring
- Use Case 1: Candlestick charts in MarketFinder

### Phase C — Intelligence (P2, ~1-2 weeks)
- Use Case 4: Event-level discovery
- Use Case 5: Orderbook depth analysis

### Phase D — Advanced (P3, ~2-3 weeks)
- Use Case 2: Trade flow & whale detection
- Use Case 7: Historical backtesting

---

## Open Questions

1. **Rate limit tier** — Are we on Basic (20 reads/sec)? Higher tiers unlock more aggressive polling.
2. **Orderbook auth** — `GET /markets/{ticker}/orderbook` requires authentication. Confirm our API key has access.
3. **Historical data scope** — How far back does Kalshi's historical API go? Need to check `/historical/cutoff`.
4. **Chart library** — `lightweight-charts` (TradingView) vs `recharts` vs `victory` for candlestick rendering.
5. **Phase 5 alignment** — Use Cases 2 and 5 (trade flow, orderbook) produce structured signals that feed directly into the Phase 5 LLM narrative layer. Should they be prioritized alongside Phase 5?
