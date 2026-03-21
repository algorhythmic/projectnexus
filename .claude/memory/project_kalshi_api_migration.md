---
name: Kalshi API field migration (Jan–Mar 2026)
description: Kalshi removed legacy field names in Jan–Mar 2026. The adapter was updated 2026-03-19 to use _dollars/_fp fields. Prices are FixedPointDollars strings.
type: project
---

Kalshi migrated their REST and WebSocket API field names between Jan–Mar 2026, removing legacy fields entirely by Mar 12, 2026.

**Why:** Kalshi introduced subpenny pricing and fractional contracts, requiring higher-precision string representations (`FixedPointDollars`, `FixedPointCount`) instead of integer cents/counts.

**How to apply:** All Kalshi data fields are now strings with `_dollars` or `_fp` suffixes. When parsing prices, use `float(val)` but guard against `"0.0000"` (truthy string but means "no data"). The `_calculate_yes_price` function uses a loop with `price <= 0` check to handle both string and numeric zeros. See [kalshi_api_reference.md](kalshi_api_reference.md) for full field list.

**Key gotcha:** The string `"0.0000"` is truthy in Python but represents "no orders/no trades." Using `or` chains (like `val_a or val_b`) will short-circuit on `"0.0000"` instead of falling through. The adapter now uses explicit iteration with `float(val) > 0` checks.
