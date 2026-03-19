# CLAUDE.md — MarketFinder

## What Is This Project

MarketFinder is a **read-only presentation layer** for prediction market intelligence data. It's a React + Convex webapp that displays data synced from **ProjectNexus** (a separate Python pipeline running on Fly.io).

The architecture doc is at `docs/ARCHITECTURE.md`.

## Relationship to ProjectNexus

MarketFinder and ProjectNexus are **separate repos** connected only by a Convex sync layer:

- **ProjectNexus** (`C:\Workspace\Code\projectnexus`, repo: `algorhythmic/projectnexus`): Python pipeline that ingests from Kalshi/Polymarket APIs, runs anomaly detection and topic clustering, and syncs results to Convex via HTTP API `internalMutation` calls.
- **MarketFinder** (this repo, `algorhythmic/marketfinder`): React webapp that reads from Convex via reactive `useQuery` subscriptions.
- **Data flows one direction**: Nexus → Convex → MarketFinder. This app never writes to sync tables.

### When changes require coordination

- **Schema changes** to sync tables (`nexusMarkets`, `activeAnomalies`, `trendingTopics`, `marketSummaries`) must match between `convex/nexusSync.ts` here and `sql/convex/nexusSync.ts` in projectnexus. The mutation paths (e.g., `nexusSync:upsertMarkets`) are hardcoded in the Python sync layer.
- **New sync tables** require changes in both repos: schema + mutation here, sync logic + materialized view in projectnexus.
- **Query-only changes** (new `queries.ts` functions, new React components) are local to this repo.

## Tech Stack

- **React 18.2.0** with Vite 6.2.0
- **Convex ^1.24.2** for reactive backend (queries, mutations, auth)
- **@convex-dev/auth ^0.0.80** with Password + Anonymous providers
- **TanStack React Table 8.21.3** for data tables
- **Tailwind CSS** with neobrutalist design system
- **lucide-react** for icons
- **Radix UI** primitives (dialog, select, checkbox, dropdown-menu, etc.)
- **shadcn/ui** component library in `src/components/ui/`

## Convex Deployment

- **Active deployment**: `deafening-starling-749` (`.env.local` has `CONVEX_DEPLOYMENT=dev:deafening-starling-749`)
- **Cloud URL**: `https://deafening-starling-749.convex.cloud`
- **Nexus sync**: Fly.io instance pushes data every 30s–5min via `CONVEX_DEPLOYMENT_URL` + `CONVEX_DEPLOY_KEY` secrets

## Repository Layout

```
marketfinder/
├── convex/                    # Convex backend
│   ├── schema.ts              # 6 app tables + authTables
│   ├── nexusSync.ts           # internalMutation handlers (Nexus pushes here)
│   ├── queries.ts             # Public query functions (React reads these)
│   ├── users.ts               # User alerts + preferences mutations
│   ├── auth.ts                # Auth setup (loggedInUser query)
│   ├── auth.config.ts         # Provider config
│   ├── crons.ts               # Empty (no cron jobs — Nexus handles ingestion)
│   ├── http.ts                # HTTP routes for auth
│   └── router.ts              # httpRouter placeholder
├── src/
│   ├── components/
│   │   ├── Dashboard.tsx          # View router (state-based, no React Router)
│   │   ├── DashboardOverview.tsx  # Main dashboard with stats cards
│   │   ├── MarketsView.tsx        # Market table with search/filter
│   │   ├── AnomalyFeedView.tsx    # Anomaly alerts feed
│   │   ├── TrendingTopicsView.tsx  # Topic cluster cards
│   │   ├── AlertsView.tsx         # User alert notifications
│   │   ├── SettingsView.tsx       # User preferences
│   │   ├── NeobrutalistSidebar.tsx # Navigation sidebar
│   │   ├── markettablecolumns.tsx  # TanStack column definitions
│   │   ├── marketdatatable.tsx     # TanStack table wrapper
│   │   ├── ThemeToggle.tsx        # Dark mode toggle
│   │   └── ui/                    # shadcn/ui primitives
│   ├── App.tsx                # Auth gate (SignInForm vs Dashboard)
│   ├── SignInForm.tsx         # Login page
│   ├── SignOutButton.tsx      # Logout button
│   ├── hooks/use-debounce.ts  # Debounce hook for search
│   └── main.tsx               # Entry point
├── docs/ARCHITECTURE.md       # System architecture reference
├── .env.local                 # Convex deployment target (gitignored)
└── package.json
```

## Code Conventions

### Routing
State-based routing via `Dashboard.tsx`. The `activeView` string determines which component renders. Views: `dashboard`, `markets`, `topics`, `anomalies`, `alerts`, `settings`.

### Data Fetching
All data comes from Convex reactive queries:
```tsx
const markets = useQuery(api.queries.getMarkets, { platform, searchTerm });
const stats = useQuery(api.queries.getMarketStats);
const anomalies = useQuery(api.queries.getActiveAnomalies, { minSeverity, limit: 100 });
const topics = useQuery(api.queries.getTrendingTopics, { limit: 20 });
const syncStatus = useQuery(api.queries.getSyncStatus);
```
All `useQuery` results may be `undefined` while loading — always handle loading states.

### Design System (Neobrutalist)
- **Borders**: `border-4 border-black`
- **Shadows**: `shadow-[8px_8px_0px_0px_#000]`
- **Dark mode shadows**: `dark:shadow-[8px_8px_0px_0px_#1f2937]`
- **Bold fills**: `bg-yellow-300`, `bg-green-300`, `bg-red-300`, `bg-blue-300`
- **Dark mode**: `dark:` Tailwind modifier throughout
- **Cards**: thick borders + hard shadows + bold header colors
- **Badges**: solid color backgrounds, not outlined

### Severity Color Scale
Used in anomaly displays:
- High (>= 0.7): `bg-red-300 text-red-800` / dark: `bg-red-700 text-red-200`
- Medium (>= 0.4): `bg-yellow-300 text-yellow-800` / dark: `bg-yellow-600 text-yellow-100`
- Low (< 0.4): `bg-blue-300 text-blue-800` / dark: `bg-blue-700 text-blue-200`

### Auth
- `@convex-dev/auth` with Password + Anonymous providers
- `useQuery(api.auth.loggedInUser)` in sidebar for user info
- `getAuthUserId(ctx)` server-side for user-scoped queries/mutations
- Auth is independent of market data — unauthenticated users see nothing

## Convex Schema

### Sync tables (populated by Nexus, read-only for webapp)
- `nexusMarkets` — market data with price/volume, indexed by platform/active/search
- `activeAnomalies` — detected anomalies with severity/type, indexed by severity/type/date
- `trendingTopics` — topic clusters ranked by anomaly activity
- `marketSummaries` — aggregated market event statistics

### App-owned tables
- `users` — preferences (categories, platforms, notification toggles)
- `alerts` — user notifications (anomaly, price_change, new_market types)

## Commands Reference

```bash
# Install dependencies
npm install

# Start dev (frontend + Convex backend concurrently)
npm run dev

# Start frontend only (requires separate `npx convex dev`)
npm run dev:frontend

# Start Convex backend only
npm run dev:backend    # or: npx convex dev

# Build for production
npm run build

# Type check
npm run typecheck

# Deploy Convex schema + functions
npx convex deploy

# Push schema only (no function changes)
npx convex dev --once
```

## Browser Testing (Playwright CLI)

Playwright is installed as a CLI tool. Use it via Bash to verify UI changes.

### Dev server
- `npm run dev` starts both Vite (`http://localhost:5173`) and Convex dev concurrently
- Or run separately: `npm run dev:frontend` + `npx convex dev`
- Convex dev must be running for queries to return data

### Commands
- `npx playwright screenshot http://localhost:5173 screenshot.png` — full page capture
- `npx playwright screenshot --wait-for-timeout=3000 http://localhost:5173 screenshot.png` — wait for async data to load
- `npx playwright test` — run E2E test files
- `npx playwright codegen http://localhost:5173` — interactive recorder (user-facing)

### When to use
- After modifying components — screenshot to verify render
- After changing Convex queries — screenshot to verify data appears
- When debugging layout issues — screenshot at different viewports

### Design expectations
- Neobrutalist style: thick black borders, hard shadows, bold color fills
- Dark mode support via `dark:` Tailwind modifiers
- Loading states: skeleton/shimmer while Convex queries are `undefined`

## Important Warnings

- **Never commit `.env.local`** — it contains the Convex deployment target. It's gitignored.
- **Don't modify `convex/nexusSync.ts`** without coordinating with projectnexus — the Python sync layer calls these mutations by exact path name.
- **Don't add cron jobs** — all data ingestion happens in Nexus on Fly.io. The `crons.ts` file must remain empty.
- **Don't write to sync tables** from the webapp — they are Nexus-owned. Only `users` and `alerts` are app-owned.
- **Auth tables** (`authSessions`, `authAccounts`, etc.) are managed by `@convex-dev/auth` — don't modify them directly.
