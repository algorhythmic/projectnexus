# Milestone 4.2 — MarketFinder Webapp Updates (Refined Implementation Plan)

> **STATUS: COMPLETED & SUPERSEDED.** Milestone 4.2 was completed, then the Convex sync architecture was replaced by a REST API (2026-03-23). See `docs/phase-5-implementation-plan.md` for the current roadmap.

> This plan supersedes `docs/milestone-4.2-plan.md` with exact file paths, complete schema definitions, and phased ordering with verification gates. Designed as a handoff document for independent implementation.

## Context

**Nexus** (Python, Fly.io) ingests prediction market data from Kalshi and Polymarket, runs anomaly detection and topic clustering, and syncs precomputed results to **Convex** (`deafening-starling-749`) every 30s–5min via HTTP API. The sync layer calls `internalMutation` functions with paths like `nexusSync:upsertMarkets`.

**MarketFinder** (`marketfinder-main/`) is a React + Convex webapp that currently has its own cron jobs, ETL pipeline, and extensive mock/hardcoded data. It needs to become a **read-only presentation layer** for Nexus-synced data.

**Goal:** Wire MarketFinder to read from Nexus-synced Convex tables. Replace mock data. Replace arbitrage features with anomaly detection. Deploy to `deafening-starling-749`.

**Working directory:** `C:/workspace/code/projectnexus/marketfinder-main/`

---

## Key Design Decisions

1. **Keep Nexus table names as-is** (`nexusMarkets`, `activeAnomalies`, `trendingTopics`, `marketSummaries`). The `nexus` prefix distinguishes sync-target tables from webapp-owned tables. No changes to `nexus/sync/sync.py` or `sql/convex/nexusSync.ts`.

2. **Eliminate the `platforms` FK table.** Use `platform` as a plain string (`"kalshi"` | `"polymarket"`). Platform display names derived in frontend.

3. **Replace Arbitrage with Anomalies.** ArbitrageView → AnomalyFeedView. Nexus detects anomalous price/volume movements, not arbitrage.

4. **Replace Market Groups with Trending Topics.** MarketGroupsView → TrendingTopicsView. Nexus's `trendingTopics` table (from `topic_clusters`) serves the same conceptual role.

5. **No cron jobs.** All data ingestion happens in Nexus on Fly.io. The Convex backend is read-only.

6. **Auth stays.** `@convex-dev/auth` with Password + Anonymous providers. Auth is independent of market data.

7. **No `syncStatus` table.** Each Nexus sync table already has a `syncedAt` field per record. The `getSyncStatus` query derives last-sync from the most recent record in each table.

---

## Architecture Reference

### Nexus Sync Layer (already running)

The Python sync layer (`nexus/sync/sync.py`) calls Convex HTTP API mutations:
- `POST {deployment_url}/api/mutation` with `Authorization: Convex {deploy_key}`
- Mutation paths: `nexusSync:upsertMarkets`, `nexusSync:upsertAnomalies`, `nexusSync:upsertTrendingTopics`, `nexusSync:upsertMarketSummaries`
- Sync frequencies: markets every 30s, anomalies every 30s, summaries every 120s, topics every 300s

The sync mutations are defined at `sql/convex/nexusSync.ts` and must be copied into the MarketFinder `convex/` directory **unchanged** (filename must be `nexusSync.ts` to match the mutation paths).

### Convex Deployment

- **Target:** `deafening-starling-749` (fresh deployment for Nexus sync)
- **Old deployment:** `sensible-parakeet-564` (stale MarketFinder, do NOT use)
- **Fly.io secrets:** `CONVEX_DEPLOYMENT_URL=https://deafening-starling-749.convex.cloud`, `CONVEX_DEPLOY_KEY` already set

### MarketFinder Tech Stack

- React 18.2.0, Vite 6.2.0
- Convex ^1.24.2, @convex-dev/auth ^0.0.80
- TanStack React Table 8.21.3
- Tailwind CSS with **neobrutalist design**: thick borders (`border-4 border-black`), hard shadows (`shadow-[8px_8px_0px_0px_#000]`), bold colors (`bg-yellow-300`, `bg-green-300`), dark mode via `dark:` modifier
- State-based routing (no React Router): `Dashboard.tsx` manages `activeView` string, renders views conditionally
- Data fetching: `useQuery(api.module.function)` for Convex reactive queries

### Key Existing Files to Read First

These files provide the best orientation for understanding the codebase patterns:
- `src/components/Dashboard.tsx` — view router, layout structure
- `src/components/NeobrutalistSidebar.tsx` — navigation, uses `api.auth.loggedInUser` query
- `src/components/DashboardOverview.tsx` — heaviest mock data, all the patterns to replace
- `convex/schema.ts` — current 14-table schema (being replaced)
- `convex/auth.ts` — auth setup, exports `loggedInUser` query (must keep)
- `sql/convex/nexusSync.ts` — source for the sync mutations file
- `sql/convex/nexusSyncSchema.ts` — reference for sync table definitions

---

## Phase 0: Prerequisites

**0.1** — Node.js is installed (v24.14.0 confirmed).

**0.2** — Install dependencies:
```bash
cd C:/workspace/code/projectnexus/marketfinder-main
npm install
```

**0.3** — Set deployment target. Create `marketfinder-main/.env.local`:
```
CONVEX_DEPLOYMENT=deafening-starling-749
```
This tells `npx convex dev` and `npx convex deploy` to target the fresh Nexus deployment.

---

## Phase 1: Convex Backend

**Must be fully deployable before touching React.** Running `npx convex dev --once` regenerates `convex/_generated/` which provides the TypeScript types that React components import.

### Step 1.1 — Rewrite `convex/schema.ts`

**Action:** Replace entire file

New schema keeps:
- 4 Nexus sync tables (from `sql/convex/nexusSyncSchema.ts`, unchanged)
- Simplified `users` table (remove FK to deleted `platforms` table, remove `clerkId`/`minProfitMargin`)
- Simplified `alerts` table (replace `"arbitrage"` type with `"anomaly"`, remove FK data references to deleted tables)
- `...authTables` spread from `@convex-dev/auth/server`

Tables **removed entirely**: `platforms`, `markets`, `marketGroups`, `marketGroupMemberships`, `marketSimilarities`, `arbitrageOpportunities`, `userProfiles`, `priceHistory`, `etlLogs`, `platformCredentials`

```typescript
import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";
import { authTables } from "@convex-dev/auth/server";

const applicationTables = {
  // ── Nexus sync targets (populated by Nexus sync layer) ──────────

  nexusMarkets: defineTable({
    marketId: v.number(),
    platform: v.string(),
    externalId: v.string(),
    title: v.string(),
    category: v.string(),
    isActive: v.boolean(),
    lastPrice: v.optional(v.union(v.number(), v.null())),
    lastPriceTs: v.optional(v.union(v.number(), v.null())),
    lastVolume: v.optional(v.union(v.number(), v.null())),
    lastVolumeTs: v.optional(v.union(v.number(), v.null())),
    syncedAt: v.number(),
  })
    .index("by_nexus_id", ["marketId"])
    .index("by_platform", ["platform"])
    .index("by_active", ["isActive"])
    .searchIndex("search_nexus_markets", {
      searchField: "title",
      filterFields: ["platform", "category", "isActive"],
    }),

  activeAnomalies: defineTable({
    anomalyId: v.number(),
    anomalyType: v.string(),
    severity: v.number(),
    marketCount: v.number(),
    detectedAt: v.number(),
    summary: v.string(),
    metadata: v.string(),
    clusterName: v.string(),
    syncedAt: v.number(),
  })
    .index("by_anomaly_id", ["anomalyId"])
    .index("by_severity", ["severity"])
    .index("by_detected_at", ["detectedAt"])
    .index("by_type", ["anomalyType"]),

  trendingTopics: defineTable({
    clusterId: v.number(),
    name: v.string(),
    description: v.string(),
    marketCount: v.number(),
    anomalyCount: v.number(),
    maxSeverity: v.number(),
    syncedAt: v.number(),
  })
    .index("by_cluster_id", ["clusterId"])
    .index("by_anomaly_count", ["anomalyCount"]),

  marketSummaries: defineTable({
    marketId: v.number(),
    platform: v.string(),
    title: v.string(),
    category: v.string(),
    eventCount: v.number(),
    firstEventTs: v.optional(v.union(v.number(), v.null())),
    lastEventTs: v.optional(v.union(v.number(), v.null())),
    syncedAt: v.number(),
  })
    .index("by_market_id", ["marketId"])
    .index("by_platform", ["platform"]),

  // ── Webapp-owned tables ─────────────────────────────────────────

  users: defineTable({
    name: v.optional(v.string()),
    preferences: v.optional(
      v.object({
        categories: v.array(v.string()),
        platforms: v.array(v.string()),
        alertsEnabled: v.boolean(),
        emailNotifications: v.boolean(),
      })
    ),
  }),

  alerts: defineTable({
    userId: v.id("users"),
    type: v.union(
      v.literal("anomaly"),
      v.literal("price_change"),
      v.literal("new_market")
    ),
    title: v.string(),
    message: v.string(),
    data: v.optional(
      v.object({
        anomalyId: v.optional(v.number()),
        marketId: v.optional(v.number()),
      })
    ),
    isRead: v.boolean(),
    createdAt: v.number(),
  })
    .index("by_user", ["userId"])
    .index("by_created_at", ["createdAt"])
    .index("by_unread", ["userId", "isRead"]),
};

export default defineSchema({
  ...authTables,
  ...applicationTables,
});
```

**Schema design notes:**
- `users.preferences.platforms` changed from `v.array(v.id("platforms"))` to `v.array(v.string())` — no FK to deleted `platforms` table
- `users.preferences` no longer has `minProfitMargin` (arbitrage concept removed)
- `alerts.type` changed: `"arbitrage"` → `"anomaly"`
- `alerts.data` references are now plain Nexus IDs (numbers), not Convex document IDs to deleted tables
- `userProfiles` table eliminated entirely (subscription info unused by any component)

### Step 1.2 — Create `convex/nexusSync.ts`

**Action:** Copy from `sql/convex/nexusSync.ts` — **unchanged**

```bash
cp sql/convex/nexusSync.ts marketfinder-main/convex/nexusSync.ts
```

The file must be named `nexusSync.ts` because the Python sync layer calls mutations with path `nexusSync:upsertMarkets`. Contains 4 `internalMutation` functions. Field names and types already match the schema from Step 1.1.

### Step 1.3 — Create `convex/queries.ts`

**Action:** Create new file with these public query functions:

| Function | Args | Source Table | Notes |
|----------|------|-------------|-------|
| `getMarkets` | `platform?, category?, searchTerm?, count?` | `nexusMarkets` | Uses search index for text search, `by_active` index otherwise. Default count: 50 |
| `getMarketStats` | (none) | `nexusMarkets` | Returns `{totalMarkets, platformCounts, categoryCounts}` by scanning active markets |
| `getActiveAnomalies` | `minSeverity?, anomalyType?, limit?` | `activeAnomalies` | Ordered by `detectedAt` desc. Default limit: 50 |
| `getAnomalyStats` | (none) | `activeAnomalies` | Returns `{activeCount, avgSeverity, bySeverityBucket: {high, medium, low}}` |
| `getTrendingTopics` | `limit?` | `trendingTopics` | Ordered by `anomalyCount` desc. Default limit: 20 |
| `getSyncStatus` | (none) | all 4 tables | Returns latest `syncedAt` from each table (derive from most recent record) |

Severity bucket thresholds: high >= 0.7, medium >= 0.4, low < 0.4

All functions are `query` (not `mutation` or `action`) — they're read-only and benefit from Convex's reactive subscription system.

### Step 1.4 — Rewrite `convex/users.ts`

**Action:** Replace entire file

Keep only 3 functions:
- `getUserAlerts(limit?)` — query, uses `getAuthUserId` from `@convex-dev/auth/server`, reads `alerts` by user, ordered desc, default limit 50
- `markAlertsRead(alertIds)` — mutation, patches `isRead: true` with ownership check
- `updatePreferences(preferences)` — mutation, patches `users` doc with new preferences object

Remove all `userProfiles` logic, `createUserProfile`, `ensureUserProfile`, `createProfile`, `getUserProfile`, `getSubscriptionInfo`, and `platforms` FK references.

### Step 1.5 — Delete legacy Convex modules

**Delete** these 11 files from `convex/`:

| File | Reason |
|------|--------|
| `arbitrage.ts` | Arbitrage detection → replaced by Nexus anomalies |
| `etl.ts` | Old ETL pipeline → replaced by Nexus |
| `jobs.ts` | Direct API polling → replaced by Nexus |
| `marketUtils.ts` | `getMarketById` → old `markets` table gone |
| `markets.ts` | Old market queries → replaced by `queries.ts` |
| `platforms.ts` | Platforms CRUD → `platforms` table removed |
| `sampleAlerts.ts` | Mock alert injection → no longer needed |
| `sampleData.ts` | Mock market data → no longer needed |
| `semanticAnalysis.ts` | LLM similarity → replaced by Nexus clustering |
| `settings.ts` | LLM API key management → references old schema |
| `syncLogs.ts` | Sync logging for crons → table removed |

**Replace** `crons.ts` with empty export (Convex may require it if previously deployed):
```typescript
import { cronJobs } from "convex/server";
const crons = cronJobs();
export default crons;
```

### Step 1.6 — Keep unchanged

These files need **zero changes**:
- `convex/auth.ts` — exports `loggedInUser` query used by sidebar (`useQuery(api.auth.loggedInUser)` at `NeobrutalistSidebar.tsx:89`)
- `convex/auth.config.ts` — provider domain config via `CONVEX_SITE_URL`
- `convex/http.ts` — imports router, adds auth HTTP routes
- `convex/router.ts` — empty httpRouter placeholder
- `convex/tsconfig.json` — TypeScript config for Convex

### Step 1.7 — Verification gate

```bash
cd C:/workspace/code/projectnexus/marketfinder-main
npx convex dev --once
```

Must compile with no errors. After running, `convex/_generated/api.d.ts` should export modules for: `queries`, `nexusSync`, `users`, `auth`.

**Do NOT proceed to Phase 2 until this passes.** If there are errors, they will be in the Convex files — fix them before touching React components.

---

## Phase 2: React Components

All changes depend on types generated in Phase 1. The `api` import from `convex/_generated/api` will now only have the new modules.

### Step 2.1 — Update `src/components/NeobrutalistSidebar.tsx`

**Action:** Modify

- Replace `"Market Groups"` nav item → `{ title: "Trending", icon: TrendingUp, view: "topics" }`
- Replace `"Arbitrage"` nav item → `{ title: "Anomalies", icon: AlertTriangle, view: "anomalies" }`
- Remove `"Automation"` nav item entirely
- Update lucide-react imports: add `AlertTriangle`, remove `Bot` and `Users`
- `useQuery(api.auth.loggedInUser)` at line 89 stays unchanged

Final nav items array:
```typescript
const items = [
  { title: "Dashboard", url: "#", icon: Home, view: "dashboard" },
  { title: "Markets", url: "#", icon: Search, view: "markets" },
  { title: "Trending", url: "#", icon: TrendingUp, view: "topics" },
  { title: "Anomalies", url: "#", icon: AlertTriangle, view: "anomalies" },
  { title: "Alerts", url: "#", icon: Bell, view: "alerts" },
  { title: "Settings", url: "#", icon: Settings, view: "settings" },
];
```

### Step 2.2 — Update `src/components/Dashboard.tsx`

**Action:** Modify

- Remove imports: `ArbitrageView`, `MarketGroupsView`, `AutomationView`
- Add imports: `AnomalyFeedView` (from `./AnomalyFeedView`), `TrendingTopicsView` (from `./TrendingTopicsView`)
- Update `viewTitles` map: remove `arbitrage`/`groups`/`automation`, add `topics: "Trending Topics"` and `anomalies: "Anomalies"`
- Update `renderView` switch: remove old cases, add `case "topics": return <TrendingTopicsView />` and `case "anomalies": return <AnomalyFeedView />`

### Step 2.3 — Rewrite `src/components/DashboardOverview.tsx`

**Action:** Replace entire file

This is the **heaviest change**. The current file has all mock data, platform initialization, and sample data injection.

Remove ALL:
- `useEffect` calls to `initializePlatforms`, `addSampleData`, `createSampleAlerts`
- Mock stats (hardcoded 15 arbitrage, 8.3% profit margin, etc.)
- Mock trending markets list
- Mock platform status list
- Mock category counts

Replace with Convex queries:
- `useQuery(api.queries.getMarketStats)` → stats cards ("Markets Tracked", platform/category breakdowns)
- `useQuery(api.queries.getAnomalyStats)` → stats cards ("Active Anomalies", "Avg Severity")
- `useQuery(api.queries.getActiveAnomalies, { limit: 5 })` → "Recent Anomalies" panel (replaces "Top Arbitrage")
- `useQuery(api.queries.getTrendingTopics, { limit: 5 })` → "Trending Topics" panel (replaces "Trending Markets")
- `useQuery(api.queries.getSyncStatus)` → "Sync Status" panel (replaces "Platform Status")

Stats cards: Markets Tracked, Active Anomalies, Avg Severity, Last Sync

Handle loading states: all `useQuery` results may be `undefined` while loading. Show skeleton/loading UI.

**Keep the neobrutalist design style** — thick borders, hard shadows, bold color badges. Match existing component patterns from `ArbitrageView.tsx` and `MarketGroupsView.tsx` for consistency before those files are deleted.

### Step 2.4 — Rewrite `src/components/MarketsView.tsx`

**Action:** Replace entire file

Remove: volume/liquidity sliders, end date filter, calendar, "Analyze Semantics" button, "Find Arbitrage" button, all `useAction` handlers, all mock analysis results, `selectedMarketIds` state, `isAnalyzingSemantics`/`isFindingArbitrage` states.

Keep: search term (debounced via `src/hooks/use-debounce.ts`), platform filter (plain string select), table display with MarketDataTable.

Query: `useQuery(api.queries.getMarkets, { platform, searchTerm, count: 50 })`

Platform select options:
```tsx
<SelectItem value="kalshi">Kalshi</SelectItem>
<SelectItem value="polymarket">Polymarket</SelectItem>
```

Pass `undefined` for platform when "All" is selected (not the string `"all"`).

### Step 2.5 — Rewrite `src/components/markettablecolumns.tsx`

**Action:** Replace entire file

Type changes to `Doc<"nexusMarkets">` (from `convex/_generated/dataModel`).

New columns:
| Column | Accessor | Display |
|--------|----------|---------|
| Select | checkbox | Same checkbox pattern as current |
| Title | `title` | Sortable |
| Platform | `platform` | Capitalize first letter |
| Price | `lastPrice` | Format as percentage: `(value * 100).toFixed(1)%`, handle null |
| Category | `category` | Plain text |
| Last Updated | `syncedAt` | `new Date(syncedAt).toLocaleString()` |
| Actions | dropdown | "Copy External ID" |

Remove: outcomes, volume, liquidity, endDate columns.

Also modify `src/components/marketdatatable.tsx`:
- Remove client-side filtering props (`volumeRangeFilter`, `liquidityRangeFilter`, `endDateFilter`) from `DataTableProps` interface
- Remove the `processedData` useMemo that applies those filters
- All filtering now happens server-side in Convex queries

### Step 2.6 — Create `src/components/AnomalyFeedView.tsx`

**Action:** Create new file (replaces ArbitrageView)

Structure:
- Header: "Active anomalies detected by Nexus across prediction markets"
- Severity filter: dropdown with All, High (>= 0.7), Medium (0.4–0.7), Low (< 0.4)
- Type filter: dropdown with All, `single_market`, `cluster`, `cross_platform`
- Table columns: Type (badge), Severity (color-coded number), Market Count, Cluster Name, Summary, Detected At
- Query: `useQuery(api.queries.getActiveAnomalies, { minSeverity, anomalyType, limit: 100 })`
- Empty state: "No anomalies detected. Check back when Nexus identifies unusual market activity."

Severity colors:
- High (>= 0.7): `bg-red-300 text-red-800` / dark: `bg-red-700 text-red-200`
- Medium (>= 0.4): `bg-yellow-300 text-yellow-800` / dark: `bg-yellow-600 text-yellow-100`
- Low (< 0.4): `bg-blue-300 text-blue-800` / dark: `bg-blue-700 text-blue-200`

Follow neobrutalist design: `border-4 border-black`, `shadow-[8px_8px_0px_0px_#000]`

### Step 2.7 — Create `src/components/TrendingTopicsView.tsx`

**Action:** Create new file (replaces MarketGroupsView)

Structure:
- Header: "Topic clusters ranked by anomaly activity, detected by Nexus"
- Card grid layout (`grid-cols-1 md:grid-cols-2 lg:grid-cols-3`)
- Each card: topic `name` (h3), `description` (paragraph), market count badge (blue), anomaly count badge (red if > 0, gray if 0), max severity indicator (colored dot), `syncedAt` as relative time
- Query: `useQuery(api.queries.getTrendingTopics, { limit: 20 })`
- Empty state: "No trending topics detected yet. Topics appear as Nexus discovers related market clusters."

Follow neobrutalist design patterns.

### Step 2.8 — Update `src/components/AlertsView.tsx`

**Action:** Minor modify

- Change `"arbitrage"` type icon to warning icon (use `AlertTriangle` from lucide-react)
- Update type badge styling: `"anomaly"` → warning/orange styling, `"price_change"` → chart/blue styling, `"new_market"` → bell/green styling
- `useQuery(api.users.getUserAlerts)` and `useMutation(api.users.markAlertsRead)` calls stay unchanged (function signatures match)

### Step 2.9 — Simplify `src/components/SettingsView.tsx`

**Action:** Modify

Remove:
- `PlatformStatusList` component and import (queries deleted `platforms` table)
- Both `PlatformCredentialsForm` instances and import (API keys managed by Nexus)
- `LlmApiKeyForm` component and import (semantic analysis removed)
- `useQuery(api.platforms.listPlatforms)` call
- `minProfitMargin` slider (arbitrage concept removed)
- Mock `userProfile` object and all references
- "Account Information" section (referenced `subscriptionTier` from deleted `userProfiles`)

Keep:
- Category checkboxes (hardcoded list of categories)
- Platform checkboxes (hardcoded "Kalshi" and "Polymarket" as plain strings)
- Notification toggles (alerts enabled, email notifications)
- Save button calling `api.users.updatePreferences`

### Step 2.10 — Delete removed components

Delete these 6 files from `src/components/`:
- `ArbitrageView.tsx` — replaced by `AnomalyFeedView.tsx`
- `MarketGroupsView.tsx` — replaced by `TrendingTopicsView.tsx`
- `AutomationView.tsx` — placeholder with no backend, deferred
- `PlatformCredentialsForm.tsx` — API keys managed by Nexus
- `PlatformStatusList.tsx` — queries deleted `platforms` table
- `LlmApiKeyForm.tsx` — semantic analysis removed

### Step 2.11 — Verification gate

```bash
cd C:/workspace/code/projectnexus/marketfinder-main
npx convex dev --once   # Recompile Convex + regenerate types
npm run build           # Full Vite build — must pass with no errors
```

Both must pass. If `npm run build` has type errors, they point to component files still referencing deleted APIs.

---

## Phase 3: Deploy & Verify

### Step 3.1 — Deploy Convex

```bash
cd C:/workspace/code/projectnexus/marketfinder-main
npx convex deploy
```

Pushes to `deafening-starling-749`. Confirm deletion of any old tables if prompted. Since this is a fresh deployment, there should be no conflicts.

### Step 3.2 — Verify Nexus sync

The Nexus instance on Fly.io already has `CONVEX_DEPLOYMENT_URL=https://deafening-starling-749.convex.cloud` and `CONVEX_DEPLOY_KEY` set as secrets.

Check Fly logs for sync activity:
```bash
fly logs --app nexus
```

Look for `sync_markets`, `sync_anomalies`, `sync_trending_topics`, `sync_market_summaries` log lines. Data should appear in Convex within 30 seconds to 5 minutes.

### Step 3.3 — Run webapp locally

```bash
cd C:/workspace/code/projectnexus/marketfinder-main
npm run dev
```

**Verification checklist:**
1. Login page renders (Anonymous auth works)
2. Dashboard shows real data from Convex (not mock data)
3. Markets view: Kalshi + Polymarket markets with search and platform filter
4. Trending Topics: topic clusters (may be empty if no clusters detected yet)
5. Anomalies: active anomaly alerts (may be empty if none active)
6. Alerts: renders (empty is fine — no alert generation mechanism yet)
7. Settings: simplified preferences, no credential forms
8. Sidebar: Dashboard, Markets, Trending, Anomalies, Alerts, Settings
9. Real-time updates: Convex subscriptions auto-update when Nexus pushes new data

---

## Complete File Summary

### Convex backend (`marketfinder-main/convex/`)

| File | Action | Step |
|------|--------|------|
| `schema.ts` | Rewrite | 1.1 |
| `nexusSync.ts` | Create — copy from `sql/convex/nexusSync.ts` | 1.2 |
| `queries.ts` | Create | 1.3 |
| `users.ts` | Rewrite | 1.4 |
| `crons.ts` | Replace with empty export | 1.5 |
| `arbitrage.ts` | Delete | 1.5 |
| `etl.ts` | Delete | 1.5 |
| `jobs.ts` | Delete | 1.5 |
| `marketUtils.ts` | Delete | 1.5 |
| `markets.ts` | Delete | 1.5 |
| `platforms.ts` | Delete | 1.5 |
| `sampleAlerts.ts` | Delete | 1.5 |
| `sampleData.ts` | Delete | 1.5 |
| `semanticAnalysis.ts` | Delete | 1.5 |
| `settings.ts` | Delete | 1.5 |
| `syncLogs.ts` | Delete | 1.5 |
| `auth.ts` | **Keep unchanged** | 1.6 |
| `auth.config.ts` | **Keep unchanged** | 1.6 |
| `http.ts` | **Keep unchanged** | 1.6 |
| `router.ts` | **Keep unchanged** | 1.6 |
| `tsconfig.json` | **Keep unchanged** | 1.6 |

### React components (`marketfinder-main/src/components/`)

| File | Action | Step |
|------|--------|------|
| `NeobrutalistSidebar.tsx` | Modify nav items | 2.1 |
| `Dashboard.tsx` | Modify router/imports | 2.2 |
| `DashboardOverview.tsx` | Rewrite (remove mock data) | 2.3 |
| `MarketsView.tsx` | Rewrite (simplify) | 2.4 |
| `markettablecolumns.tsx` | Rewrite (new columns) | 2.5 |
| `marketdatatable.tsx` | Modify (remove client filters) | 2.5 |
| `AnomalyFeedView.tsx` | **Create new** | 2.6 |
| `TrendingTopicsView.tsx` | **Create new** | 2.7 |
| `AlertsView.tsx` | Minor modify (alert types) | 2.8 |
| `SettingsView.tsx` | Modify (remove credentials/LLM) | 2.9 |
| `ArbitrageView.tsx` | Delete | 2.10 |
| `MarketGroupsView.tsx` | Delete | 2.10 |
| `AutomationView.tsx` | Delete | 2.10 |
| `PlatformCredentialsForm.tsx` | Delete | 2.10 |
| `PlatformStatusList.tsx` | Delete | 2.10 |
| `LlmApiKeyForm.tsx` | Delete | 2.10 |

### Files unchanged

- `src/App.tsx`, `src/main.tsx`, `src/SignInForm.tsx`, `src/SignOutButton.tsx`
- `src/hooks/use-debounce.ts`
- `src/components/GraphPaperBackground.tsx`, `Sidebar.tsx`, `ThemeToggle.tsx`
- All `src/components/ui/*` (Shadcn/Radix components)
- `package.json`, `vite.config.ts`, `tailwind.config.js`

### Nexus-side: **No changes required**

The sync layer's mutation paths (`nexusSync:upsertMarkets`, etc.) and field names already match the new schema.

---

## Dependency Graph

```
Phase 0: npm install + .env.local
    │
Phase 1: Convex backend
    ├── Step 1.1: schema.ts (must be first — all other files depend on it)
    ├── Step 1.2: nexusSync.ts (depends on schema)
    ├── Step 1.3: queries.ts (depends on schema)
    ├── Step 1.4: users.ts (depends on schema)
    ├── Step 1.5: Delete legacy files (parallel with 1.2–1.4)
    └── Step 1.7: npx convex dev --once (VERIFICATION GATE)
            │
Phase 2: React components (depends on Phase 1 passing)
    ├── Step 2.1: Sidebar (independent)
    ├── Step 2.2: Dashboard router (depends on 2.6 + 2.7 files existing)
    ├── Step 2.3: DashboardOverview (depends on queries.ts types)
    ├── Step 2.4: MarketsView (depends on Step 2.5)
    ├── Step 2.5: Table columns + data table (depends on schema types)
    ├── Step 2.6: AnomalyFeedView (depends on queries.ts types)
    ├── Step 2.7: TrendingTopicsView (depends on queries.ts types)
    ├── Step 2.8: AlertsView (depends on users.ts types)
    ├── Step 2.9: SettingsView (depends on users.ts types)
    ├── Step 2.10: Delete old components (after all references removed)
    └── Step 2.11: npm run build (VERIFICATION GATE)
            │
Phase 3: Deploy + verify
    ├── Step 3.1: npx convex deploy
    ├── Step 3.2: Verify Nexus sync (Fly.io logs)
    └── Step 3.3: npm run dev (manual verification)
```
