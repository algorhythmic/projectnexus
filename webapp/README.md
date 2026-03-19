# MarketFinder

A read-only presentation layer for prediction market intelligence, powered by data from [ProjectNexus](https://github.com/algorhythmic/projectnexus).

## How It Works

MarketFinder displays prediction market data that is ingested, analyzed, and synced by ProjectNexus — a separate Python pipeline running on Fly.io.

```
ProjectNexus (Python, Fly.io)              Convex                          MarketFinder (React)
┌───────────────────────────┐     ┌───────────────────────┐     ┌──────────────────────────┐
│ Kalshi API ──┐            │     │                       │     │ Dashboard (stats, feed)  │
│ Polymarket ──┤ Ingest     │     │ nexusMarkets          │     │ Markets (table + cards)  │
│              ├─► Anomaly  │────►│ activeAnomalies       │────►│ Anomalies (table + cards)│
│              │   Detection│HTTP │ trendingTopics        │live │ Trending Topics          │
│              └─► Topic    │sync │ marketSummaries       │query│ Alerts & Settings        │
│                  Cluster  │     │                       │     │                          │
└───────────────────────────┘     └───────────────────────┘     └──────────────────────────┘
```

**Data flows one direction**: Nexus → Convex → MarketFinder. This app never writes to sync tables.

## Tech Stack

- **React 18** with **Vite 6** — frontend framework and build tool
- **Convex** — reactive backend (queries, mutations, auth)
- **TanStack React Table** — sortable, selectable data tables with responsive card layout on mobile
- **Tailwind CSS** — neobrutalist design system (thick borders, hard shadows, bold fills)
- **Radix UI / shadcn/ui** — accessible component primitives
- **Playwright** — browser screenshots for visual verification

## Data Sources (via ProjectNexus)

MarketFinder does not connect to prediction market APIs directly. All data arrives pre-processed from ProjectNexus:

| Sync Table | Source | Refresh Rate | Description |
|---|---|---|---|
| `nexusMarkets` | Kalshi + Polymarket | 30s | 10,000+ markets with price/volume data |
| `activeAnomalies` | Nexus anomaly detector | 30s | Price and volume anomalies with severity scores |
| `trendingTopics` | Nexus topic clustering | 5min | Market clusters grouped by topic similarity |
| `marketSummaries` | Nexus aggregator | 2min | Per-market event statistics |

ProjectNexus syncs to Convex via HTTP `internalMutation` calls using these exact paths:
- `nexusSync:upsertMarkets`
- `nexusSync:upsertAnomalies`
- `nexusSync:upsertMarketSummaries`
- `nexusSync:upsertTrendingTopics`

## Getting Started

```bash
# Install dependencies
npm install

# Start dev server (frontend + Convex backend)
npm run dev

# The app requires ProjectNexus to be running and syncing data to Convex.
# Without Nexus, tables will be empty but the UI will still load.
```

Requires a `.env.local` file with `CONVEX_DEPLOYMENT` set (gitignored, not committed).

## Convex Deployment

| Deployment | Instance | Purpose |
|---|---|---|
| **Dev (active)** | `deafening-starling-749` | Shared by Nexus sync + MarketFinder |
| **Prod** | `glad-cricket` | Not yet deployed |

## Coordinating Changes with ProjectNexus

Most changes to this repo are **query-only** (new components, new query functions, UI updates) and require no coordination.

Changes that **do** require coordination across both repos:

| Change | This Repo | ProjectNexus |
|---|---|---|
| Modify sync table schema | Update `convex/schema.ts` | Update `sql/convex/nexusSync.ts` |
| Add new sync table | Add to schema + `nexusSync.ts` | Add materialized view + sync logic |
| Rename mutation path | Update `convex/nexusSync.ts` | Update hardcoded mutation paths in sync layer |

**Do not** modify `convex/nexusSync.ts` without a corresponding change in ProjectNexus — the Python sync layer calls these mutations by exact path name.

## Project Structure

```
marketfinder/
├── convex/                     # Convex backend
│   ├── schema.ts               # 6 app tables + authTables
│   ├── nexusSync.ts            # Mutation handlers (Nexus pushes here)
│   ├── queries.ts              # Public query functions (React reads these)
│   ├── users.ts                # User preferences mutations
│   └── auth.ts                 # Auth setup
├── src/
│   ├── components/
│   │   ├── Dashboard.tsx       # View router (state-based)
│   │   ├── DashboardOverview   # Stats cards, anomaly feed, trending topics
│   │   ├── MarketsView.tsx     # Market table with search, filter, compare
│   │   ├── AnomalyFeedView.tsx # Anomaly table with severity/type filters
│   │   ├── MarketComparisonDialog.tsx  # Side-by-side market comparison
│   │   ├── AnomalyDetailDialog.tsx     # Expanded anomaly metadata view
│   │   ├── marketdatatable.tsx # Responsive DataTable (table + card modes)
│   │   └── ui/                 # shadcn/ui primitives
│   └── hooks/
│       ├── use-debounce.ts     # Search debounce
│       └── use-responsive-layout.ts  # Mobile/tablet/desktop detection
├── docs/ARCHITECTURE.md        # Detailed architecture and decision history
└── screens/                    # Playwright screenshots (gitignored)
```

## Architecture Details

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full architecture document, including:
- Platform API reference (Kalshi, Polymarket)
- Cross-platform category mapping
- Architecture decision history (why Nexus was separated from MarketFinder)
- Deployment details
