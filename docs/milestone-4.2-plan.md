# Milestone 4.2 — MarketFinder Webapp Updates

> **STATUS: COMPLETED & SUPERSEDED.** Milestone 4.2 was completed, then the Convex sync architecture was replaced by a REST API (2026-03-23). See `docs/phase-5-implementation-plan.md` for the current roadmap.

## Context

Nexus (Python) is deployed to Fly.io, ingesting data from Kalshi and Polymarket, running anomaly detection, topic clustering, and cross-platform correlation. The sync layer pushes precomputed data from PostgreSQL views to Convex every 30s-5min via HTTP API.

The MarketFinder webapp (React + Convex) currently has its own Convex backend with cron jobs that poll platform APIs directly, plus extensive mock/hardcoded data in dashboard views. The legacy Convex deployment (`sensible-parakeet-564`) has stale data and broken crons. We need to scrap it, deploy a clean Convex backend that consumes Nexus-synced data, and update the webapp views accordingly.

**Goal:** Wire MarketFinder to read from Nexus-synced Convex tables. Replace mock data. Replace arbitrage features with anomaly detection features. Deploy to a fresh Convex deployment.

---

## Prerequisite: Install Node.js

Node.js is not installed. Required for `npx convex deploy`, `npm install`, and running the webapp.

```bash
winget install OpenJS.NodeJS.LTS
```

Then `cd marketfinder-main && npm install`.

---

## Key Design Decisions

1. **Keep Nexus table names as-is** (`nexusMarkets`, `activeAnomalies`, `trendingTopics`, `marketSummaries`). The `nexus` prefix distinguishes sync-target tables from any future webapp-owned tables. No changes needed to `nexus/sync/sync.py` or `sql/convex/nexusSync.ts`.

2. **Eliminate `platforms` FK table.** The old schema joined markets -> platforms by `v.id("platforms")`. The new schema uses `platform` as a plain string (`"kalshi"` | `"polymarket"`). Platform display names are derived in the frontend.

3. **Replace Arbitrage with Anomalies.** ArbitrageView -> AnomalyFeedView. Nexus doesn't compute arbitrage; it detects anomalous price/volume movements and cross-platform correlations.

4. **Replace Market Groups with Trending Topics.** MarketGroupsView -> TrendingTopicsView. Nexus's `trendingTopics` table (from `topic_clusters`) serves the same conceptual role.

5. **No cron jobs.** All data ingestion happens in Nexus (Fly.io). The Convex backend is a read-only presentation layer populated by the sync layer.

6. **Auth stays.** Keep `@convex-dev/auth` setup unchanged. User auth is independent of market data.

---

## Implementation Steps

### Step 1: New Convex Schema (`convex/schema.ts`)

Replace the entire schema. New tables:

| Table | Source | Purpose |
|-------|--------|---------|
| `nexusMarkets` | Nexus sync (30s) | Current market state |
| `activeAnomalies` | Nexus sync (30s) | Live anomaly alerts |
| `trendingTopics` | Nexus sync (5min) | Topic clusters ranked by anomaly activity |
| `marketSummaries` | Nexus sync (2min) | Per-market event stats |
| `alerts` | Webapp mutations | User notifications |
| `syncStatus` | Nexus sync | Last sync timestamps per target |
| auth tables | `@convex-dev/auth` | Authentication |

Schema comes from existing `sql/convex/nexusSyncSchema.ts` plus `alerts` and `syncStatus` tables.

**Files:** `marketfinder-main/convex/schema.ts`

### Step 2: Deploy Sync Mutations (`convex/nexusSync.ts`)

Copy existing `sql/convex/nexusSync.ts` into the MarketFinder convex directory. Add a `syncStatus` update at the end of each mutation (so the dashboard can show last sync time).

**Files:** `marketfinder-main/convex/nexusSync.ts`

### Step 3: New Convex Query Functions (`convex/queries.ts`)

Public queries for the webapp to consume:

- `getMarkets({platform?, category?, searchTerm?, count?})` -- Read from `nexusMarkets`. Search by title via search index. Filter by platform string and category.
- `getMarketStats()` -- Return `{totalMarkets, platformCounts, categoryCounts}` from `nexusMarkets`.
- `getActiveAnomalies({minSeverity?, anomalyType?, limit?})` -- Read from `activeAnomalies`, sorted by detectedAt desc.
- `getAnomalyStats()` -- Return `{activeCount, avgSeverity, bySeverityBucket}`.
- `getTrendingTopics({limit?})` -- Read from `trendingTopics`, sorted by anomalyCount desc.
- `getSyncStatus()` -- Read from `syncStatus` table, return last sync timestamps.

**Files:** `marketfinder-main/convex/queries.ts`

### Step 4: User/Alert Functions (`convex/users.ts`)

Keep `getUserAlerts` and `markAlertsRead`. Update alert types from `"arbitrage"` to `"anomaly"`. Remove references to `platforms` table and `platformCredentials`.

**Files:** `marketfinder-main/convex/users.ts`

### Step 5: Remove Dead Convex Modules

Delete these files (no longer needed):
- `convex/etl.ts` -- ETL pipeline functions
- `convex/jobs.ts` -- Direct API polling crons
- `convex/arbitrage.ts` -- Simple arbitrage detection
- `convex/sampleData.ts` -- Mock data injection
- `convex/sampleAlerts.ts` -- Mock alerts
- `convex/syncLogs.ts` -- Old sync logging
- `convex/platforms.ts` -- Platforms table CRUD
- `convex/semanticAnalysis.ts` -- LLM similarity analysis
- `convex/markets.ts` -- Old market queries (replaced by `queries.ts`)

Empty out `convex/crons.ts` (no crons needed).

### Step 6: Sidebar Navigation (`src/components/NeobrutalistSidebar.tsx`)

Update menu items:
- "Market Groups" -> **"Trending"** (icon: `TrendingUp`, view: `"topics"`)
- "Arbitrage" -> **"Anomalies"** (icon: `AlertTriangle`, view: `"anomalies"`)
- Keep: Dashboard, Markets, Alerts, Settings
- Remove or keep: Automation (placeholder)

### Step 7: DashboardOverview (`src/components/DashboardOverview.tsx`)

Replace all mock data with Convex queries:

- **Stats cards:** "Active Anomalies" (from `getAnomalyStats`), "Avg Severity", "Markets Tracked" (from `getMarketStats`), "Last Sync" (from `getSyncStatus`)
- **"Top Arbitrage"** -> **"Recent Anomalies"** panel (top 5 from `getActiveAnomalies`)
- **"Markets by Category"** -> powered by `getMarketStats().categoryCounts`
- **"Trending Markets"** -> **"Trending Topics"** (from `getTrendingTopics`)
- **"Platform Status"** -> Sync status showing Kalshi/Polymarket last sync times
- **Remove** `initializePlatforms`, `addSampleData`, `createSampleAlerts` useEffect

### Step 8: MarketsView (`src/components/MarketsView.tsx`)

Simplify:
- **Platform filter:** String select (`"all"` | `"kalshi"` | `"polymarket"`) instead of `v.id("platforms")`
- **Remove:** Volume/liquidity range sliders, end date filter, "Analyze Semantics" button, "Find Arbitrage" button
- **Keep:** Search term filter, category filter (if categories are known)
- **Query:** `useQuery(api.queries.getMarkets, {platform, searchTerm, count})`

### Step 9: Market Table Columns (`src/components/markettablecolumns.tsx`)

New columns: Select (checkbox), Title, Platform (string), Price (lastPrice as %), Category, Last Updated (syncedAt), Actions.

Remove: outcomes column, liquidity column, endDate column.

### Step 10: AnomalyFeedView (new, replaces ArbitrageView)

`src/components/AnomalyFeedView.tsx`

- Severity filter (dropdown: All, High >0.7, Medium 0.4-0.7, Low <0.4)
- Type filter (all, single_market, cluster, cross_platform)
- Table: Anomaly Type badge, Severity (color-coded), Market Count, Cluster Name, Summary, Detected At
- Uses `useQuery(api.queries.getActiveAnomalies, {minSeverity, anomalyType, limit})`

### Step 11: TrendingTopicsView (new, replaces MarketGroupsView)

`src/components/TrendingTopicsView.tsx`

- Card layout showing: topic name, description, market count badge, anomaly count badge, max severity indicator
- Uses `useQuery(api.queries.getTrendingTopics, {limit})`

### Step 12: Dashboard Router (`src/components/Dashboard.tsx`)

- Import AnomalyFeedView, TrendingTopicsView
- Remove ArbitrageView, MarketGroupsView imports
- Update switch cases: `"anomalies"` -> AnomalyFeedView, `"topics"` -> TrendingTopicsView
- Update viewTitles accordingly

### Step 13: Alerts & Settings Updates

- AlertsView: Change `"arbitrage"` type icon to `"anomaly"` warning icon
- SettingsView: Remove PlatformCredentialsForm (API keys managed by Nexus, not webapp users)

### Step 14: Deploy & Verify

1. Set `CONVEX_DEPLOYMENT=deafening-starling-749` in marketfinder-main
2. `npx convex deploy` to push new schema + functions
3. Update Fly.io `CONVEX_DEPLOYMENT_URL` secret to point to same deployment
4. Verify Nexus sync layer pushes data successfully
5. `npm run dev` to test webapp locally
6. Verify: markets appear, anomalies render, trending topics show, sync status updates in real-time

---

## Files Modified (MarketFinder)

| File | Action |
|------|--------|
| `convex/schema.ts` | Rewrite |
| `convex/nexusSync.ts` | New (from sql/convex/) |
| `convex/queries.ts` | New |
| `convex/users.ts` | Simplify |
| `convex/auth.ts`, `convex/auth.config.ts` | Keep as-is |
| `convex/crons.ts` | Empty |
| `convex/etl.ts`, `jobs.ts`, `arbitrage.ts`, `sampleData.ts`, `sampleAlerts.ts`, `syncLogs.ts`, `platforms.ts`, `semanticAnalysis.ts`, `markets.ts` | Delete |
| `src/components/Dashboard.tsx` | Update router |
| `src/components/NeobrutalistSidebar.tsx` | Update nav items |
| `src/components/DashboardOverview.tsx` | Rewrite (remove mock data) |
| `src/components/MarketsView.tsx` | Simplify filters, new query |
| `src/components/markettablecolumns.tsx` | New column definitions |
| `src/components/AnomalyFeedView.tsx` | New (replaces ArbitrageView) |
| `src/components/TrendingTopicsView.tsx` | New (replaces MarketGroupsView) |
| `src/components/ArbitrageView.tsx` | Delete |
| `src/components/MarketGroupsView.tsx` | Delete |
| `src/components/AlertsView.tsx` | Minor update |
| `src/components/SettingsView.tsx` | Simplify |

## Files Modified (Nexus)

None required. The sync layer's mutation paths and field names align with the new schema.

---

## Verification

1. `npx convex deploy` succeeds with no type errors
2. Nexus sync layer on Fly.io pushes data to the new deployment (check Fly logs)
3. `npm run dev` -- webapp loads, dashboard shows real data from Convex
4. Markets view shows Kalshi + Polymarket markets with search/filter working
5. Anomalies view shows active anomaly alerts (may be empty if no anomalies detected yet)
6. Trending Topics view shows topic clusters
7. Sync status in dashboard reflects recent sync timestamps
8. Real-time updates: changing data in PostgreSQL -> sync pushes -> UI updates automatically
