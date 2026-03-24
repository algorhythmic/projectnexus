# Phase 5 — Intelligence Layer: Implementation Plan

> Revised 2026-03-23, post REST API migration

## Context

Phases 1–4 are complete. The architecture migration (2026-03-23) replaced Convex broadcast sync with a REST API on Fly.io. The data pipeline runs on Fly.io (`shared-cpu-1x`, 1GB RAM) with 4 concurrent asyncio tasks: ingestion, detection, sync (PG → BroadcastCache), and REST API server.

This plan covers the remaining work to validate the spec's three hypotheses and reach the Track 2 decision gate.

### What Exists

| Component | Status | Location |
|---|---|---|
| Single-market anomaly detection | Complete | `nexus/correlation/detector.py` |
| Cluster correlation | Complete | `nexus/correlation/correlator.py` |
| Series pattern detection | Complete | `nexus/correlation/series_detector.py` |
| Cross-platform correlation | Complete | `nexus/correlation/cross_platform.py` |
| Market health scoring | Complete | `nexus/intelligence/health.py` |
| CatalystAnalysis dataclass | Complete | `nexus/intelligence/narrative.py` |
| CatalystAnalyzer.analyze_events() | Complete | `nexus/intelligence/narrative.py` |
| REST API (7 endpoints) | Complete | `nexus/api/app.py` |
| BroadcastCache + ETag | Complete | `nexus/api/cache.py` |
| SyncLayer (PG → cache) | Complete | `nexus/sync/sync.py` |
| useNexusQuery hook | Complete | `webapp/src/hooks/use-nexus-query.ts` |
| Webapp views (markets, anomalies, topics, dashboard) | Complete | `webapp/src/components/` |
| Convex alerts table + AlertsView | Complete (read-only) | `convex/schema.ts`, `webapp/src/components/AlertsView.tsx` |
| Topic clustering (LLM-based) | Complete (CLI only) | `nexus/correlation/correlator.py`, `nexus/cli.py` |

### What's Missing

| Gap | Impact |
|---|---|
| CatalystAnalyzer not wired into DetectionLoop | Anomaly metadata has no catalyst context |
| No template alert renderer | No human-readable narrative output |
| No LLM narrative generator | Hypothesis C untested |
| No alert creation pipeline | Convex `alerts` table is empty — nothing creates alert records |
| No news API integration | LLM has no external context to attribute catalysts |
| Topic clustering never run in production | `/api/v1/topics` returns empty; TrendingTopicsView is blank |
| No formal hypothesis validation metrics | No instrumented signal quality audit |
| REST API not yet deployed with latest code | `fly deploy` needed |
| Webapp not deployed to Vercel | End-to-end flow not verified |

---

## Milestone 5.0 — Deploy & Validate (Operational)

**Goal:** Ship what's built, verify end-to-end, establish hypothesis validation baselines.

**Duration:** 1–2 days active work + 7 days observation.

**Status (verified 2026-03-23):**
- Step 5.0.1 DONE — Fly.io REST API live at `https://projectnexus.fly.dev` (3,959 markets, 823 anomalies)
- Step 5.0.2 DONE — Webapp live at `https://marketfinder.daviddunn.dev` (Vite build, wired to Fly.io API)
- Step 5.0.3 DONE — Convex `deafening-starling-749` serving auth + per-user features
- Step 5.0.4 IN PROGRESS — 7-day stability observation starts now

### Step 5.0.1 — Deploy REST API to Fly.io

**What:** Deploy the updated Fly.io image with the REST API server.

**Commands:**
```bash
fly deploy                                    # From repo root
fly logs --app projectnexus | head -50        # Verify startup
curl https://projectnexus.fly.dev/api/v1/status  # Verify API responds
```

**Verify:**
- `fly.toml` `[http_service]` routes port 8080 correctly
- Health check at `/api/v1/status` passes (15s interval, 5s timeout)
- `/api/v1/markets` returns data (populated from PG materialized views)
- `/api/v1/anomalies` returns data (may be empty during off-hours)

**Risk:** The Fly.io image now runs uvicorn alongside the pipeline. If RSS + API overhead exceeds 1GB, OOM restarts will resume. Baseline without API was ~78MB off-peak, ~156MB post-discovery. Uvicorn + Starlette should add <20MB.

### Step 5.0.2 — Deploy Webapp to Vercel

**What:** Deploy MarketFinder with `VITE_NEXUS_API_URL` pointing to the Fly.io API.

**Pre-requisites:**
- Vercel project linked to `algorhythmic/projectnexus`
- Root directory set to `webapp/`
- Build command: `npm run build` (which runs `vite build`)
- Output directory: `dist/`
- Environment variable: `VITE_NEXUS_API_URL=https://projectnexus.fly.dev`

**Verify:**
- DashboardOverview shows market stats, anomaly stats, sync timestamps
- MarketsView shows markets table with sorting/filtering
- AnomalyFeedView shows anomalies (during market hours)
- TrendingTopicsView shows empty state (clustering not yet run)
- AlertsView shows "no alerts" state (alert creation not yet implemented)
- Auth works (sign in, sign out, anonymous)

### Step 5.0.3 — Deploy Convex Schema

**What:** Deploy the slimmed-down Convex schema (auth + users/alerts only).

**Commands:**
```bash
npx convex dev --once                         # From repo root
```

**Verify:**
- No broadcast tables in Convex dashboard
- Auth tables present (`authSessions`, `authAccounts`, etc.)
- `users` and `alerts` tables present
- No function errors in Convex logs

### Step 5.0.4 — 7-Day Stability Observation

**Goal:** Validate Hypothesis A (stable connections, reliable detection) and establish baselines for Hypothesis B.

**Metrics to collect daily (from `fly logs`):**

| Metric | Where | Target |
|---|---|---|
| `rss_mb` | Pipeline health logs (every 60s) | < 800MB peak, < 200MB baseline |
| `rss_delta_mb` | Detection cycle logs | < 50MB per cycle |
| `anomalies_found` | Detection cycle logs | Count per day |
| `markets_scanned` | Detection cycle logs | Should be ~200 (cap) during hours |
| `ws_disconnect` | Error category logs | < 5/day |
| `rate_limit_hit` | Error category logs | 0 (we're well under limits) |
| API response time | `/api/v1/status` lastRefresh deltas | < 60s staleness |

**Daily checklist:**
1. Check Fly.io dashboard for OOM restarts (should be 0)
2. Count anomalies detected: target < 50/day at current thresholds
3. Note if anomaly volume is too high or too low (threshold tuning)
4. Spot-check 3–5 anomalies: do they correspond to real market movements?
5. Record any pipeline errors or connection drops

**Output:** A `docs/stability-report.md` with daily observations and a go/no-go decision for Phase 5.

### Files Modified
- None (deployment only)

### Files Created
- `docs/stability-report.md` (after observation period)

---

## Milestone 5.1 — Wire Catalyst Attribution + Template Alerts

**Goal:** Connect `CatalystAnalyzer` into the detection pipeline and produce template-based human-readable alerts. This is the **control condition** for Hypothesis C.

**Duration:** 2–3 days.

### Step 5.1.1 — Wire CatalystAnalyzer into DetectionLoop

**What:** After `AnomalyDetector.detect_and_store()` runs, analyze each new anomaly's events with `CatalystAnalyzer` and store the result in anomaly metadata.

**File:** `nexus/correlation/detection_loop.py`

**Changes:**
1. Import `CatalystAnalyzer` from `nexus.intelligence.narrative`
2. Instantiate in `__init__` (no deps needed, it's stateless)
3. After `detect_and_store()` returns new anomaly count:
   - For each new anomaly, fetch events + market record
   - Call `analyzer.analyze_events(events, market, window_minutes)`
   - Update the anomaly's `metadata` field with `CatalystAnalysis.to_dict()`
4. Log catalyst type distribution per cycle

**Data flow:**
```
DetectionLoop.run_once()
  → AnomalyDetector.detect_and_store() → anomaly_ids[]
  → For each new anomaly:
      → store.get_events(market_id, window) → events[]
      → store.get_market(market_id) → market
      → CatalystAnalyzer.analyze_events(events, market, window) → CatalystAnalysis
      → store.update_anomaly_metadata(anomaly_id, catalyst.to_dict())
```

**Implementation notes:**
- `CatalystAnalyzer` already exists and works — just needs wiring
- `detect_and_store()` currently returns an int (count). We need the anomaly IDs to update metadata. Either:
  - (a) Modify `detect_and_store()` to return `List[Tuple[int, int, int]]` (anomaly_id, market_id, window_minutes), or
  - (b) Add a `detect_and_store_with_context()` method, or
  - (c) Query recently-created anomalies after the call
- Option (a) is cleanest — minimal API change, direct access to context

**Store changes:**
- Add `update_anomaly_metadata(anomaly_id: int, metadata: dict)` to `BaseStore` / `PostgresStore`
- SQL: `UPDATE anomalies SET metadata = $2 WHERE id = $1`

### Step 5.1.2 — Template Alert Renderer

**What:** Create a template engine that transforms `CatalystAnalysis` into structured English summaries.

**File (new):** `nexus/intelligence/templates.py`

**Design:**
```python
class TemplateRenderer:
    """Renders CatalystAnalysis into human-readable alert text."""

    def render(self, analysis: CatalystAnalysis, market_title: str) -> str:
        """Produce a 2-4 sentence summary of the anomaly."""
        ...

    def render_structured(self, analysis: CatalystAnalysis, market_title: str) -> dict:
        """Produce a structured alert object for the REST API."""
        return {
            "headline": "...",        # One-liner
            "narrative": "...",       # 2-4 sentences
            "catalyst_type": "...",   # From CatalystAnalysis
            "confidence": 0.0-1.0,
            "signals": [...],         # Key evidence points
        }
```

**Template logic by catalyst_type:**
- `"whale"` → "Large trades drove {market}: {whale_pct}% of volume came from trades over $500..."
- `"news"` → "A burst of activity hit {market}: {trades_per_minute} trades/min concentrated in {burst_duration}s..."
- `"momentum"` → "Sustained {direction} pressure on {market}: {trade_count} trades pushed price {magnitude}%..."
- `"pre_resolution"` → "{market} is {hours_to_expiry}h from expiry and saw a {magnitude}% move..."
- `"unknown"` → "{market} moved {magnitude}% {direction} with {trade_count} trades..."

**Each template includes:**
- Market title and direction
- Key numeric evidence (magnitude, trade count, whale %)
- Time context (window, burst duration, expiry proximity)

### Step 5.1.3 — Enrich Anomaly REST API Response

**What:** Include rendered template text in the anomaly API response.

**File:** `nexus/sync/sync.py` (in `sync_anomalies()`)

**Changes:**
- Parse the `metadata` JSON from each anomaly row
- If metadata contains `catalyst_type` (i.e., CatalystAnalysis was stored):
  - Instantiate `TemplateRenderer` and call `render_structured()`
  - Add `"catalyst"` field to the anomaly record in the cache
- If metadata is empty/missing catalyst: `"catalyst": null`

**REST API response change (anomaly record):**
```json
{
  "anomalyId": 42,
  "anomalyType": "single_market",
  "severity": 0.35,
  "summary": "BTC Price: +5.2% (0.45→0.47)...",
  "catalyst": {
    "headline": "Whale-driven surge on BTC >50k market",
    "narrative": "Large trades drove BTC...",
    "catalyst_type": "whale",
    "confidence": 0.65,
    "signals": ["62% whale volume", "burst: 45 trades in 12s"]
  },
  ...
}
```

**Webapp changes:**
- `webapp/src/types/nexus.ts` — add `catalyst?: CatalystInfo` to `NexusAnomaly`
- `webapp/src/components/AnomalyFeedView.tsx` — display catalyst headline and narrative instead of raw metadata JSON
- `webapp/src/components/AnomalyDetailDialog.tsx` — show full catalyst breakdown (signals, confidence, type)

### Step 5.1.4 — Tests

**New test files:**
- `tests/test_templates.py` — Unit tests for `TemplateRenderer` with various `CatalystAnalysis` inputs
- Update `tests/test_api.py` — Add anomaly records with catalyst field to sample data

**Test cases:**
- Each catalyst_type produces appropriate narrative text
- Missing/empty catalyst gracefully returns null
- Structured output has all required fields
- Integration: detection → catalyst → metadata → cache → API response

### Files Modified
- `nexus/correlation/detection_loop.py` — Wire CatalystAnalyzer
- `nexus/correlation/detector.py` — Return anomaly context (ids + market_ids + windows)
- `nexus/store/base.py` — Add `update_anomaly_metadata()` abstract method
- `nexus/store/postgres.py` — Implement `update_anomaly_metadata()`
- `nexus/store/sqlite.py` — Implement `update_anomaly_metadata()` (for tests)
- `nexus/sync/sync.py` — Parse catalyst from metadata, render template
- `nexus/api/app.py` — No change (cache already serves whatever sync puts in)
- `webapp/src/types/nexus.ts` — Add `CatalystInfo` interface
- `webapp/src/components/AnomalyFeedView.tsx` — Display catalyst narrative
- `webapp/src/components/AnomalyDetailDialog.tsx` — Show catalyst details
- `tests/test_api.py` — Update sample data

### Files Created
- `nexus/intelligence/templates.py` — Template renderer
- `tests/test_templates.py` — Template tests

---

## Milestone 5.2 — Topic Clustering & Alert Pipeline

**Goal:** Populate trending topics and build the alert creation bridge from Python to Convex.

**Duration:** 2–3 days.

### Step 5.2.1 — Run Initial Topic Clustering

**What:** Execute `nexus cluster` against the production database to populate topic clusters.

**Pre-requisite:** `ANTHROPIC_API_KEY` must be set (locally or as Fly.io secret).

**Commands:**
```bash
# Local (with POSTGRES_DSN pointing to Supabase):
python -m poetry run nexus cluster --mode batch --dry-run  # Preview
python -m poetry run nexus cluster --mode batch            # Execute

# Verify:
python -m poetry run nexus db-stats                        # Check cluster counts
curl https://projectnexus.fly.dev/api/v1/topics            # Should return topics after next sync cycle
```

**Expected outcome:**
- ~50–200 topic clusters created from ~4000 active markets
- `v_trending_topics` materialized view populated
- `/api/v1/topics` returns data
- TrendingTopicsView in webapp shows topics

**Cost estimate:** ~4000 markets ÷ 30 per batch = ~133 Claude API calls. At ~1000 tokens/call with claude-sonnet: ~$0.40.

### Step 5.2.2 — Scheduled Clustering on Fly.io

**What:** Add periodic re-clustering to the pipeline so new markets get assigned to topics.

**File:** `nexus/correlation/detection_loop.py` or new `nexus/correlation/cluster_loop.py`

**Design options:**
- (a) Add a clustering task to the existing TaskGroup (runs every 6h)
- (b) Trigger incremental clustering at the end of each detection cycle (if new unassigned markets exist)
- (c) CLI cron via `fly machines run` on a schedule

**Recommended:** Option (b) — incremental clustering after detection, gated by a timer (every 6 hours) and a minimum unassigned market count (>10). This keeps it in-process and avoids external scheduling.

**Implementation:**
```python
# In DetectionLoop.__init__:
self._last_cluster_ts = 0.0
self._cluster_interval = 6 * 3600  # 6 hours

# In DetectionLoop.run_once(), after detection:
if (now - self._last_cluster_ts > self._cluster_interval
    and settings.anthropic_api_key):
    unassigned = await self._store.count_unassigned_markets()
    if unassigned > 10:
        await self._run_incremental_clustering()
        self._last_cluster_ts = now
```

**Store changes:**
- Add `count_unassigned_markets() -> int` to `BaseStore` / `PostgresStore`
- SQL: `SELECT COUNT(*) FROM markets WHERE id NOT IN (SELECT market_id FROM market_cluster_memberships) AND is_active = true`

### Step 5.2.3 — Alert Creation Pipeline

**What:** Create alerts in the Convex `alerts` table when anomalies match user preferences.

**Architecture decision:** Alerts are per-user (different users want different alerts based on their category/platform preferences). This means alert creation needs to:
1. Know which anomalies are new (not previously alerted)
2. Match anomalies against each user's preferences
3. Create Convex `alerts` records via HTTP API

**File (new):** `nexus/alerts/creator.py`

**Design:**
```python
class AlertCreator(LoggerMixin):
    """Creates per-user alerts in Convex when new anomalies match preferences."""

    def __init__(self, convex_client: ConvexClient):
        self._convex = convex_client
        self._last_alert_ts: float = 0.0
        self._alerted_anomaly_ids: set = set()  # Dedup within session

    async def process_new_anomalies(self, anomalies: List[dict]) -> int:
        """Match new anomalies against user preferences and create alerts."""
        # 1. Fetch all users with alertsEnabled=True from Convex
        # 2. For each anomaly not in _alerted_anomaly_ids:
        #    - For each user whose preferences match (category, platform):
        #      - Create alert record via Convex mutation
        # 3. Return count of alerts created
```

**Convex changes:**
- Add new mutation in `convex/alerts.ts`:
  ```typescript
  export const createAlert = mutation({
    args: { userId: v.id("users"), type: v.string(), title: v.string(), message: v.string(), data: v.optional(...) },
    handler: async (ctx, args) => { ... }
  })

  export const getAlertableUsers = query({
    args: {},
    handler: async (ctx) => {
      // Return users with alertsEnabled=true and their preferences
    }
  })
  ```

**Integration point:** Called from `SyncLayer.sync_anomalies()` after cache update — compare previous vs current anomaly IDs, process new ones through `AlertCreator`.

**Throttling:**
- Max 10 alerts per user per hour (configurable)
- Dedup: same anomaly_id never alerted twice
- Batch creation: one Convex mutation with multiple alerts (not one mutation per alert)

### Step 5.2.4 — Tests

- `tests/test_alert_creator.py` — Mock ConvexClient, verify preference matching, dedup, throttling
- Update clustering tests if incremental trigger logic is added

### Files Modified
- `nexus/correlation/detection_loop.py` — Add incremental clustering trigger
- `nexus/store/base.py` — Add `count_unassigned_markets()`
- `nexus/store/postgres.py` — Implement `count_unassigned_markets()`
- `nexus/store/sqlite.py` — Implement `count_unassigned_markets()` (for tests)
- `nexus/sync/sync.py` — Trigger alert creation on new anomalies
- `nexus/sync/convex_client.py` — Still used for alert creation (per-user Convex data)

### Files Created
- `nexus/alerts/__init__.py`
- `nexus/alerts/creator.py` — Alert creation + preference matching
- `convex/alerts.ts` — Convex mutations for alert CRUD
- `tests/test_alert_creator.py`

---

## Milestone 5.3 — LLM Narrative Layer (Hypothesis C)

**Goal:** Add LLM-powered catalyst attribution that correlates anomaly context with external news. Run both template and LLM systems in parallel to evaluate Hypothesis C.

**Duration:** 3–5 days.

### Step 5.3.1 — News API Integration

**What:** Fetch recent news headlines related to a market's topic when an anomaly fires.

**File (new):** `nexus/intelligence/news.py`

**Design:**
```python
class NewsProvider(LoggerMixin):
    """Fetches recent news relevant to a market or topic."""

    async def search(self, query: str, hours_back: int = 6) -> List[NewsItem]:
        """Search for recent news articles matching query."""
        ...

@dataclass
class NewsItem:
    title: str
    source: str
    published_at: str   # ISO timestamp
    url: str
    snippet: str        # First ~200 chars of article
```

**API options (evaluate in order of preference):**
1. **Google News RSS** — Free, no API key. Parse `https://news.google.com/rss/search?q={query}`. Limited but sufficient for MVP.
2. **NewsAPI.org** — Free tier: 100 requests/day. Richer metadata.
3. **Adjacent News API** (`docs.adj.news`) — Prediction-market-specific news. May have the best signal. Check pricing.

**Recommended for MVP:** Google News RSS. No API key, no cost, good enough to test the hypothesis. Upgrade later if signal quality matters.

**Cache:** Cache news results per query for 30 minutes to avoid redundant fetches. In-memory dict with TTL.

### Step 5.3.2 — LLM Narrative Generator

**What:** Pass anomaly context (CatalystAnalysis + news headlines + market context) to Claude to produce a narrative explanation.

**File (new):** `nexus/intelligence/llm_narrator.py`

**Design:**
```python
class LLMNarrator(LoggerMixin):
    """Generates narrative explanations for anomalies using Claude."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def narrate(
        self,
        catalyst: CatalystAnalysis,
        market_title: str,
        news: List[NewsItem],
        cluster_context: Optional[str] = None,
    ) -> NarrativeResult:
        """Generate an LLM-powered narrative for an anomaly."""
        ...

@dataclass
class NarrativeResult:
    headline: str           # One-line summary
    narrative: str          # 3-5 sentence explanation
    attributed_catalyst: str  # Best guess: news headline, data release, etc.
    confidence: float       # 0-1
    news_sources: List[str] # URLs of news used
    model: str              # Model used
    tokens_used: int        # For cost tracking
    latency_ms: int         # For performance tracking
```

**Prompt design (system):**
```
You are an analyst explaining why a prediction market moved.
Given the market data, trading signals, and recent news, write:
1. A one-line headline
2. A 3-5 sentence narrative explaining the most likely catalyst
3. Your confidence level (0-1) in the attribution

Be specific. Reference concrete evidence from the trading data and news.
If no news explains the move, say so — attribute to technical factors.
```

**Prompt design (user):**
```
Market: {market_title}
Direction: {direction} ({magnitude}%)
Window: {window_minutes} minutes

Trading signals:
- {trade_count} trades, {trades_per_minute}/min
- Whale activity: {whale_pct}% of volume
- Taker imbalance: {taker_buy_pct}% buy-side
- Burst detected: {burst_detected} ({burst_duration}s)

Recent news:
{formatted_news_list}

Market context:
- Category: {category}
- Series: {series_prefix} ({markets_in_series} markets)
- Hours to expiry: {hours_to_expiry}
```

**Cost estimate:** ~500 input tokens + ~200 output tokens per anomaly. At claude-sonnet pricing (~$3/$15 per 1M tokens): ~$0.004/anomaly. At 20 anomalies/day: ~$0.08/day.

### Step 5.3.3 — Parallel Execution in Detection Loop

**What:** Run both template and LLM narratives for each anomaly, store both for comparison.

**File:** `nexus/correlation/detection_loop.py`

**Changes to the catalyst phase (after Step 5.1.1 wiring):**

```python
# After CatalystAnalysis is computed:
template_result = template_renderer.render_structured(catalyst, market_title)

llm_result = None
if settings.anthropic_api_key:
    news = await news_provider.search(market_title, hours_back=6)
    llm_result = await llm_narrator.narrate(catalyst, market_title, news)

# Store both in metadata
metadata = {
    **catalyst.to_dict(),
    "template_narrative": template_result,
    "llm_narrative": llm_result.to_dict() if llm_result else None,
}
await store.update_anomaly_metadata(anomaly_id, metadata)
```

**REST API change:** The `catalyst` field in anomaly responses gains a `source` indicator:
```json
{
  "catalyst": {
    "headline": "...",
    "narrative": "...",
    "source": "llm",        // or "template" if LLM unavailable
    "llm_available": true,   // Flag for A/B comparison
    "template_headline": "...",
    "llm_headline": "..."
  }
}
```

### Step 5.3.4 — Evaluation Dashboard

**What:** A simple way to compare template vs. LLM narratives side-by-side.

**Options:**
- (a) CLI command: `nexus evaluate` — fetches recent anomalies, displays template vs. LLM side-by-side in terminal
- (b) Webapp component: `NarrativeComparisonView` — shows both narratives, lets user vote which is better
- (c) Log-based: Store both, export to CSV after 2 weeks, blind-evaluate offline

**Recommended for MVP:** Option (a) + (c). CLI for quick inspection, CSV export for formal evaluation. A webapp component is nice-to-have but not needed to validate Hypothesis C.

**CLI command:**
```bash
nexus evaluate --days 7 --format table   # Side-by-side terminal view
nexus evaluate --days 14 --format csv    # Export for blind evaluation
```

### Step 5.3.5 — Tests

- `tests/test_news.py` — Mock RSS/API responses, verify parsing
- `tests/test_llm_narrator.py` — Mock Claude API, verify prompt construction, response parsing
- `tests/test_narrative_integration.py` — End-to-end: catalyst → news → LLM → structured output

### Files Modified
- `nexus/correlation/detection_loop.py` — Add LLM narrator alongside template
- `nexus/sync/sync.py` — Source selection (LLM preferred, template fallback)
- `nexus/cli.py` — Add `evaluate` command
- `pyproject.toml` — Add `anthropic` SDK dependency (if not already present)
- `webapp/src/types/nexus.ts` — Extend CatalystInfo with source/comparison fields
- `webapp/src/components/AnomalyDetailDialog.tsx` — Show source indicator

### Files Created
- `nexus/intelligence/news.py` — News API integration
- `nexus/intelligence/llm_narrator.py` — Claude-powered narrative generator
- `tests/test_news.py`
- `tests/test_llm_narrator.py`

### Dependencies Added
- `anthropic` — Claude SDK (check if already in pyproject.toml)
- `feedparser` — RSS parsing for Google News (lightweight, stdlib alternative is xml.etree)

---

## Milestone 5.4 — Hypothesis Evaluation & Decision Gate

**Goal:** Formally evaluate Hypotheses A, B, and C. Decide on Track 2.

**Duration:** 2 weeks observation + 1 day analysis.

### Step 5.4.1 — Hypothesis A Evaluation

**Criteria (from spec):**
- Stable WebSocket connections for 72+ continuous hours — check Fly.io uptime logs
- 100K+ events stored — check `nexus db-stats`
- 5+ genuine correlated market movements in one week — check cluster + series anomalies
- All failure modes documented — from stability report

**Output:** Section in `docs/hypothesis-evaluation.md`

### Step 5.4.2 — Hypothesis B Evaluation

**Criteria (from spec):**
- < 50 alerts/day at default thresholds
- > 60% of alerts correspond to verifiable real-world catalysts

**Method:**
1. Run `nexus evaluate --days 14 --format csv`
2. Sample 50 anomalies randomly
3. For each: check if the summary/catalyst matches a real news event
4. Calculate hit rate

**Output:** Section in `docs/hypothesis-evaluation.md`

### Step 5.4.3 — Hypothesis C Evaluation

**Criteria (from spec):**
- Blind evaluator prefers LLM-generated alert 70%+ of the time

**Method:**
1. Export paired template/LLM narratives from the 2-week parallel run
2. Randomize order (hide which is template vs. LLM)
3. Rate each pair: which better explains what happened?
4. Calculate preference rate

**Output:** Section in `docs/hypothesis-evaluation.md`

### Step 5.4.4 — Track 2 Decision

Based on evaluation results:
- **If A + B pass:** System is operationally sound and produces useful signals → proceed to Track 2
- **If C passes (70%+ preference):** Keep LLM layer, optimize cost/latency
- **If C fails:** Drop LLM, use template alerts (already working), save the API cost
- **Track 2A (Personal Trading):** Monitor for 3+ tradeable opportunities/month
- **Track 2B (Product):** Define MVP API surface, recruit 10 beta users

### Files Created
- `docs/hypothesis-evaluation.md` — Formal evaluation document
- `docs/stability-report.md` — 7-day stability observations (from 5.0.4)

---

## Dependency Graph

```
5.0.1 (Deploy Fly.io) ─────┐
5.0.2 (Deploy Vercel) ──────┤
5.0.3 (Deploy Convex) ──────┼─→ 5.0.4 (7-day observation)
                             │
                             └─→ 5.1.1 (Wire CatalystAnalyzer) ──→ 5.1.2 (Template renderer)
                                                                       │
                                 5.2.1 (Run clustering) ←── (parallel) │
                                   │                                    │
                                 5.2.2 (Scheduled clustering)          │
                                   │                                    │
                                 5.2.3 (Alert pipeline) ←─── 5.1.3 (Enrich API)
                                                                       │
                                                                    5.1.4 (Tests)
                                                                       │
                                 5.3.1 (News API) ────────────────────┤
                                   │                                    │
                                 5.3.2 (LLM narrator) ←───────────────┘
                                   │
                                 5.3.3 (Parallel execution)
                                   │
                                 5.3.4 (Evaluation CLI)
                                   │
                                 5.3.5 (Tests)
                                   │
                                 5.4 (Hypothesis evaluation — after 2 weeks)
```

## Summary Table

| Milestone | Focus | Duration | Key Deliverable |
|---|---|---|---|
| **5.0** | Deploy & validate | 1–2 days + 7 days observation | Stability report, end-to-end verification |
| **5.1** | Template alerts | 2–3 days | CatalystAnalyzer wired, template narratives in API |
| **5.2** | Topics + alert pipeline | 2–3 days | Trending topics live, per-user alerts created |
| **5.3** | LLM narrative | 3–5 days | News-enriched LLM narratives, A/B comparison |
| **5.4** | Hypothesis evaluation | 2 weeks + 1 day | Formal evaluation, Track 2 decision |

**Total active development:** ~10–14 days
**Total elapsed time (including observation):** ~4–5 weeks
