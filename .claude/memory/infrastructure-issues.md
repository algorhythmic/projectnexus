---
name: Infrastructure resource issues
description: Supabase exceeding 500MB free tier, Fly.io OOM kills at 1GB, Convex nearing read limits — all caused by 144K+ accumulated market rows
type: project
---

## Supabase DB Over 500MB Free Tier (discovered 2026-03-18)

**Space used:** 0.68 GB (limit: 500 MB)
**Disk usage:** 1.45 GB (includes WAL)

| Object | Size | Notes |
|--------|------|-------|
| `public.markets` | 397 MB (57%) | 144K+ rows accumulated from unlimited discovery |
| `public.v_market_summaries` | 183 MB (26%) | Materialized view duplicating markets data |
| `public.markets_platform_external_id_key` | 89 MB (13%) | UNIQUE index |
| `public.v_current_market_state` | 86 MB (12%) | Materialized view with LATERAL joins |

**Root cause:** Discovery was paginating 30 pages × 200 = 6000 markets/cycle, each cycle finding different markets due to API cursor instability, accumulating 144K+ over time. Most are inactive combo/prop markets that never receive events.

**Fixes applied:**
- Discovery reduced to 5 pages (1000 markets/cycle)
- `mve_filter=exclude` skips multivariate combo markets
- `min_close_ts` skips near-expiry markets
- Only markets with events synced to Convex (597 vs 90K+)
- `v_market_summaries` refresh reduced from 2min to 30min
- `v_current_market_state` refresh reduced from 30s to 5min

**Still needed:** Purge stale markets from `markets` table (144K rows where most have zero events). This would reclaim ~350MB and bring Supabase under the 500MB limit.

## Fly.io OOM (discovered 2026-03-18)

**VM:** shared-cpu-1x, 1GB RAM. Average RSS: 730 MB.

**Cause:** Detection cycle scanned all markets with historical events on first boot (`_last_cycle_ts=0`), each requiring 4 windows × 3 event queries + baseline sampling over remote Supabase connection.

**Fixes applied:**
- `_last_cycle_ts` initialized to 10 minutes ago (not 0)
- Markets capped at 200 per detection cycle
- Reduced sync volume (597 markets vs 90K+)

**Why:** The 1GB VM leaves ~230MB headroom after baseline Python + asyncpg + httpx. Detection must stay within that budget.

**RSS monitoring added (2026-03-19):**
- `rss_mb` in pipeline health logs every 60s
- `rss_before_mb`, `rss_after_mb`, `rss_delta_mb` in detection cycle logs
- Off-peak baseline: ~78 MB — healthy headroom
- **TODO:** Check fly logs during peak hours (9:30 AM–8 PM ET) to verify OOM fixes hold. Look for `rss_mb` trending toward 900+ or large `rss_delta_mb` values.
- `nexus detect --lookback N --cap N` available for local profiling without deploying

**How to apply:** Check peak-hour `rss_mb` in fly logs. If consistently > 800 MB, either lower `--cap` or upgrade to 2GB (`fly scale memory 2048`, ~$3.50/mo more).

## Convex Read Limits (discovered 2026-03-18)

**Critical insights on dashboard:**
- `queries:getMarkets` — "Nearing documents read limit" (scanning 90K+ nexusMarkets)
- `queries:getMarketStats` — same issue (aggregating all markets)

**Fix applied:** Only sync markets with events (597 instead of 90K+). This should eliminate the read limit warnings once old documents age out or are purged.
