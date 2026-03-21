---
name: Anomaly detection threshold tuning and improvements
description: Detection thresholds, severity scoring, summary enrichment, and deduplication — calibrated for prediction market data on 2026-03-18
type: project
---

## Thresholds (set via `fly secrets set` on 2026-03-18)
- `ANOMALY_PRICE_CHANGE_THRESHOLD`: 0.10 → 0.03 (3%)
- `ANOMALY_VOLUME_SPIKE_MULTIPLIER`: 3.0 → 2.0
- `ANOMALY_ZSCORE_THRESHOLD`: 2.5 → 1.5

**Why:** Prediction markets are probability-bounded (0-1) with typical moves of 1-3%. Old thresholds produced zero anomalies.

## Severity Scoring (commit 611ec56)
Changed from linear `min(1.0, change/threshold)` to logarithmic `log10(ratio+1)/log10(101)`.

**Why:** Linear scoring caused ALL anomalies to cap at 1.00 (any move above 3% scored max). Logarithmic gives: 2x threshold → 0.15, 5x → 0.35, 10x → 0.50, 100x → 1.0.

## Summary Enrichment (commit 611ec56)
Summaries now include market title + price from/to:
- Before: `"market_id=637989: +166.7% price in 1440min window"`
- After: `"Will X happen? +5.2% (50%→55%) in 15min window"`

Uses `get_market_by_id()` with in-memory title cache.

## Deduplication (commits bdd09ec, 611ec56)
- Markets with existing active anomalies are skipped (single SQL JOIN query)
- Only highest-severity window stored per market per cycle
- Old N+1 query approach replaced with `get_markets_with_active_anomalies()`

## Known Issues
- Only 1440min window anomalies firing (short windows don't exceed 3% during off-hours)
- Topic clusters empty — `nexus cluster` never run (requires ANTHROPIC_API_KEY + LLM cost)
- No VOLUME_UPDATE events emitted — only TRADE, with trade count as volume proxy
- Kalshi trading hours: most activity 9:30 AM–8 PM ET weekdays

**How to apply:** Monitor during peak hours. May need to lower thresholds further or adjust windows. Consider removing 1440min window (overlaps with 24h baseline period).
