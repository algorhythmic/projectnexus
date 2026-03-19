# MarketFinder Architecture

## Current Architecture (post-Milestone 4.2)

MarketFinder is a **read-only presentation layer** for prediction market data synced from ProjectNexus.

```
Nexus (Python, Fly.io)          Convex (deafening-starling-749)          MarketFinder (React, Vite)
┌──────────────────────┐        ┌──────────────────────────────┐        ┌─────────────────────────┐
│ Kalshi API           │        │ nexusMarkets                 │        │ DashboardOverview       │
│ Polymarket API       │──sync──│ activeAnomalies              │──live──│ MarketsView             │
│ Anomaly detection    │  HTTP  │ trendingTopics               │ query  │ AnomalyFeedView         │
│ Topic clustering     │  API   │ marketSummaries              │        │ TrendingTopicsView      │
└──────────────────────┘        │ users, alerts (app-owned)    │        │ AlertsView, SettingsView│
                                └──────────────────────────────┘        └─────────────────────────┘
```

**Data flows one direction**: Nexus ingests from platform APIs, runs anomaly detection and topic clustering, then syncs precomputed results to Convex via `internalMutation` calls (`nexusSync:upsertMarkets`, etc.). The webapp reads via reactive `useQuery` subscriptions.

### Tech Stack

- **Frontend**: React 18, Vite 6, TanStack React Table, Tailwind CSS (neobrutalist style)
- **Backend**: Convex (reactive queries, auth via `@convex-dev/auth`)
- **Routing**: State-based (`Dashboard.tsx` manages `activeView` string, no React Router)
- **Design**: Neobrutalist — `border-4 border-black`, `shadow-[8px_8px_0px_0px_#000]`, bold color fills, dark mode via `dark:` modifier

### Convex Schema (6 tables + auth)

| Table | Owner | Purpose |
|-------|-------|---------|
| `nexusMarkets` | Nexus | Market data from Kalshi/Polymarket |
| `activeAnomalies` | Nexus | Detected price/volume anomalies |
| `trendingTopics` | Nexus | Topic clusters by market similarity |
| `marketSummaries` | Nexus | Aggregated market statistics |
| `users` | App | User preferences |
| `alerts` | App | User-facing alerts |

### Sync Frequencies (Nexus → Convex)

| Data | Interval | Mutation Path |
|------|----------|---------------|
| Markets | 30s | `nexusSync:upsertMarkets` |
| Anomalies | 30s | `nexusSync:upsertAnomalies` |
| Summaries | 120s | `nexusSync:upsertMarketSummaries` |
| Topics | 300s | `nexusSync:upsertTrendingTopics` |

---

## Platform API Reference

### Kalshi

| Detail | Value |
|--------|-------|
| Read endpoint | `https://trading-api.kalshi.com/v1/cached/markets/` |
| Auth | 30-minute tokens with auto-renewal at 25 min |
| Rate limit | 20 requests/second (basic tier) |
| Pagination | Cursor-based (`cursor=abc123&limit=50`) |
| Market count | ~5,000 active markets |
| Key field | `market_id` (UUID) → maps to `externalId` |
| Key note | `/cached/markets` returns ALL markets in a single response — no pagination needed |
| Categories | Politics, Sports, Culture, Crypto, Climate, Economics, Tech & Science, Health, World (9 total) |

### Polymarket

| Detail | Value |
|--------|-------|
| Read endpoint | `https://gamma-api.polymarket.com/markets` |
| Auth | None required for read-only Gamma API |
| Rate limit | No apparent limits during testing |
| Pagination | Offset-based, supports offsets up to 50,200+ |
| Market count | 50,000+ markets available |
| Key field | `condition_id` → maps to `externalId` |
| Key note | Only ~4% captured with `limit=20` batches — need `limit=100` with high batch count for full coverage |
| CLOB API | `https://clob.polymarket.com` — requires HMAC auth for trading, not needed for read-only |

### Cross-Platform Category Mapping

```
Kalshi "Politics"       → "politics"
Kalshi "Sports"         → "sports"
Kalshi "Crypto"         → "crypto"
Kalshi "Tech & Science" → "technology"
Polymarket "Science"    → "technology"
Polymarket "Business"   → "economics"
Polymarket "Entertainment" → "culture"
(unmapped)              → "other"
```

---

## Architecture Decision History

### Problem: Convex Bandwidth Overflow

The original MarketFinder attempted to run the full ETL pipeline (API ingestion, semantic matching, arbitrage detection) inside Convex functions and Vercel serverless.

- **161M+ market comparisons** per run (Cartesian product of cross-platform markets)
- **$161K theoretical Convex cost** per full run
- **45 hours processing time** — impractical for production
- Vercel Functions: 2 cron limit, 15-minute timeout caused constant failures

### Solution: Nexus Separation (Milestone 4.0–4.2)

Split into two systems:

1. **ProjectNexus** (Python, Fly.io): handles all data ingestion, anomaly detection, and topic clustering. Uses DuckDB for analytical queries, runs on dedicated compute ($15–25/month).
2. **MarketFinder** (React, Convex): read-only webapp consuming precomputed data via Convex reactive queries.

**Result**: 99.97% cost reduction ($1,630 → $20/month), 1,350x speed improvement, Convex operations dropped from 161M to <1,000 per sync cycle.

### Why Anomalies Instead of Arbitrage

The original vision was cross-platform arbitrage detection via LLM-powered semantic market matching. This was replaced with anomaly detection because:

- Arbitrage requires real-time price comparison across platforms (latency-sensitive)
- Nexus's anomaly detection (price/volume anomalies) provides similar value with simpler infrastructure
- Topic clustering replaces market grouping with automated Nexus-detected clusters

### Deferred Features

These were in the original spec but not yet implemented:

- Portfolio tracking across platforms
- Multi-factor auth and subscription tiers
- Trading integration / order placement
- Additional platforms (PredictIt, Manifold, Augur)
- Advanced arbitrage detection with LLM semantic matching
- Real-time price streaming via WebSocket

---

## Deployment

### Convex

| Deployment | Instance | Status |
|-----------|----------|--------|
| **Dev (active)** | `deafening-starling-749` | Shared by Nexus sync + MarketFinder |
| **Prod** | `glad-cricket` | Empty, not yet deployed |
| **Old (stale)** | `sensible-parakeet-564` | Legacy MarketFinder, do NOT use |

**Deploy command**: `npx convex dev --once` (dev) — do NOT use `npx convex deploy` without specifying deployment, it defaults to prod.

### Frontend

- Hosted via Vite dev server locally
- No Vercel serverless functions (removed in M4.2)
- `vercel.json` is empty — no custom config needed

### Nexus (Fly.io)

- App name: `nexus`
- Secrets: `CONVEX_DEPLOYMENT_URL`, `CONVEX_DEPLOY_KEY` already configured
- Logs: `fly logs --app nexus`
