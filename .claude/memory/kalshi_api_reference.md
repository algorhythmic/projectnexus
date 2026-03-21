---
name: Kalshi API v2 Reference (as of March 2026)
description: Current Kalshi REST and WebSocket API field names, types, and deprecation status — verified against live API and docs.kalshi.com on 2026-03-19.
type: reference
---

Source: https://docs.kalshi.com (fetched 2026-03-19)
Changelog: https://docs.kalshi.com/changelog

## Breaking Changes Timeline

- **Jan 5, 2026:** `category` and `risk_limit_cents` removed from Market responses.
- **Jan 6, 2026:** Cent-denominated price fields removed: `yes_bid`, `yes_ask`, `no_bid`, `no_ask`, `last_price`, `tick_size`. Use `_dollars` equivalents.
- **Mar 3, 2026:** Deprecation notice: all legacy integer count/cents fields removed Mar 12.
- **Mar 12, 2026:** ALL legacy integer fields removed. Only `_dollars` (prices) and `_fp` (counts) remain.
- **Feb 12, 2026:** `ticker_v2` WebSocket channel removed; use `ticker`.
- **Feb 13, 2026:** `liquidity_dollars` deprecated, always returns "0.0000".

## REST: GET /trade-api/v2/markets

**URL:** `https://api.elections.kalshi.com/trade-api/v2/markets` (production, public — no auth needed)

**Query params:** `limit`, `cursor`, `status`, `min_close_ts`, `mve_filter`, `event_ticker`, `series_ticker`, `tickers`

### Market Object Fields (current)

**Identifiers:**
- `ticker` (string) — market identifier
- `event_ticker` (string) — parent event

**Content (some deprecated):**
- `title` (string) — DEPRECATED but still returned
- `subtitle` (string) — DEPRECATED but still returned
- `yes_sub_title` / `no_sub_title` (string) — shortened side titles
- `rules_primary` / `rules_secondary` (string)

**Status/Lifecycle:**
- `status` (string) — enum: `initialized`, `inactive`, `active`, `closed`, `determined`, `disputed`, `amended`, `finalized`
  - NOTE: there is NO "open" status
- `market_type` (string) — "binary" or "scalar"
- `result` (string) — "yes", "no", "scalar", or ""
- `can_close_early` (boolean)
- `fractional_trading_enabled` (boolean)

**Timestamps (ISO 8601 / date-time):**
- `created_time`, `updated_time`, `open_time`, `close_time`
- `expected_expiration_time` (nullable)
- `expiration_time` — DEPRECATED
- `latest_expiration_time`
- `settlement_timer_seconds` (integer)
- `settlement_ts` (nullable)
- `fee_waiver_expiration_time` (nullable)

**Prices (FixedPointDollars — string, up to 6 decimals, e.g. "0.5600"):**
- `yes_bid_dollars` — highest YES buy offer
- `yes_ask_dollars` — lowest YES sell offer
- `no_bid_dollars` — highest NO buy offer
- `no_ask_dollars` — lowest NO sell offer
- `last_price_dollars` — last YES trade price
- `previous_yes_bid_dollars` — 24h ago YES bid
- `previous_yes_ask_dollars` — 24h ago YES ask
- `previous_price_dollars` — 24h ago last price
- `notional_value_dollars` — contract settlement value
- `settlement_value_dollars` (nullable) — post-determination value
- `liquidity_dollars` — DEPRECATED, always "0.0000"

**Volumes/Sizes (FixedPointCount — string, 2 decimals, e.g. "10.00"):**
- `yes_bid_size_fp` — contracts at best YES bid
- `yes_ask_size_fp` — contracts at best YES ask
- `volume_fp` — total market volume
- `volume_24h_fp` — 24-hour volume
- `open_interest_fp` — open contracts

**Pricing config:**
- `response_price_units` — DEPRECATED, use `price_level_structure`
- `price_level_structure` (string) — e.g. "deci_cent"
- `price_ranges` (array) — `[{start, end, step}]`

**REMOVED fields (no longer in response):**
- `yes_ask`, `yes_bid`, `no_ask`, `no_bid`, `last_price` — removed Jan 6, 2026
- `volume`, `open_interest` — removed Mar 12, 2026
- `category`, `risk_limit_cents` — removed Jan 5, 2026
- `tick_size` — removed Jan 6, 2026

## REST: GET /trade-api/v2/markets/trades

**Trade Object Fields:**
- `trade_id` (string)
- `ticker` (string)
- `count_fp` (FixedPointCount) — contracts traded
- `yes_price_dollars` (FixedPointDollars)
- `no_price_dollars` (FixedPointDollars)
- `taker_side` (enum: "yes", "no")
- `created_time` (date-time)

**REMOVED:** `count`, `yes_price`, `no_price`

## WebSocket Connection

**URL:** `wss://api.elections.kalshi.com/trade-api/ws/v2` (production)
**Demo:** `wss://demo-api.kalshi.co/trade-api/ws/v2`

**Auth headers (for handshake):**
- `KALSHI-ACCESS-KEY`: API key ID
- `KALSHI-ACCESS-TIMESTAMP`: Unix ms
- `KALSHI-ACCESS-SIGNATURE`: RSA-PSS(SHA256) of `timestamp + "GET" + "/trade-api/ws/v2"`

**Subscription format:**
```json
{"id": 1, "cmd": "subscribe", "params": {"channels": ["ticker", "trade"], "market_tickers": ["TICKER-1"]}}
```

**Public channels:** `ticker`, `trade`, `market_lifecycle_v2`, `multivariate`
**Private channels:** `orderbook_delta`, `fill`, `market_positions`, `communications`, `order_group_updates`, `user_orders`

## WebSocket: ticker channel

Fields in `msg` object:
- `market_ticker` (string)
- `market_id` (string, UUID)
- `price_dollars` (string) — last traded price
- `yes_bid_dollars` (string) — best YES bid
- `yes_ask_dollars` (string) — best YES ask
- `volume_fp` (string) — total contracts traded
- `open_interest_fp` (string)
- `dollar_volume` (integer) — dollars traded
- `dollar_open_interest` (integer) — dollars positioned
- `ts` (integer) — Unix seconds
- `time` (string) — RFC3339 timestamp

**REMOVED from ticker:** `yes_ask`, `yes_bid`, `last_price`, `volume`, `open_interest`

## WebSocket: trade channel

Fields in `msg` object:
- `market_ticker` (string)
- `count_fp` (FixedPointCount)
- `yes_price_dollars` (FixedPointDollars)
- `no_price_dollars` (FixedPointDollars)
- `taker_side` (enum: "yes", "no")
- `ts` (integer)
- `time` (string)

**REMOVED from trade:** `count`, `yes_price`, `no_price`
