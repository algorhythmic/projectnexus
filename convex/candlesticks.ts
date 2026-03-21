/**
 * Candlestick data proxy — fetches OHLCV data from Kalshi's public API
 * and caches it in a Convex table for 60 seconds.
 *
 * Architecture: React component → Convex action → Kalshi API → cache.
 * Kalshi market data reads are public (no auth required), so the action
 * can fetch directly without RSA signing.
 */

import { action, internalMutation, internalQuery } from "./_generated/server";
import { v } from "convex/values";
import { internal } from "./_generated/api";

const KALSHI_API_BASE = "https://api.elections.kalshi.com/trade-api/v2";
const CACHE_TTL_MS = 60_000; // 60 seconds

// ── Internal helpers ─────────────────────────────────────────────

export const getCachedCandles = internalQuery({
  args: {
    ticker: v.string(),
    periodInterval: v.number(),
  },
  handler: async (ctx, args) => {
    return await ctx.db
      .query("candlestickCache")
      .withIndex("by_ticker_period", (q) =>
        q.eq("ticker", args.ticker).eq("periodInterval", args.periodInterval)
      )
      .first();
  },
});

export const upsertCachedCandles = internalMutation({
  args: {
    ticker: v.string(),
    periodInterval: v.number(),
    candles: v.array(
      v.object({
        time: v.number(),
        open: v.number(),
        high: v.number(),
        low: v.number(),
        close: v.number(),
        volume: v.number(),
      })
    ),
    fetchedAt: v.number(),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("candlestickCache")
      .withIndex("by_ticker_period", (q) =>
        q.eq("ticker", args.ticker).eq("periodInterval", args.periodInterval)
      )
      .first();

    if (existing) {
      await ctx.db.patch(existing._id, {
        candles: args.candles,
        fetchedAt: args.fetchedAt,
      });
    } else {
      await ctx.db.insert("candlestickCache", {
        ticker: args.ticker,
        periodInterval: args.periodInterval,
        candles: args.candles,
        fetchedAt: args.fetchedAt,
      });
    }
  },
});

// ── Public action ────────────────────────────────────────────────

/**
 * Fetch candlestick data for a market.
 *
 * Checks the cache first (60s TTL). On cache miss, fetches from
 * Kalshi's public API, normalizes the response, caches it, and
 * returns the data.
 *
 * The series ticker is inferred from the market ticker (first
 * segment before the first hyphen, e.g. "INXD" from "INXD-26MAR21-B5825").
 */
export const getCandlesticks = action({
  args: {
    ticker: v.string(),
    periodInterval: v.optional(v.number()),
    startTs: v.optional(v.number()),
    endTs: v.optional(v.number()),
  },
  handler: async (ctx, args) => {
    const period = args.periodInterval ?? 60;
    const now = Math.floor(Date.now() / 1000);
    const startTs = args.startTs ?? now - 86400; // 24h ago
    const endTs = args.endTs ?? now;

    // 1. Check cache
    const cached = await ctx.runQuery(
      internal.candlesticks.getCachedCandles,
      { ticker: args.ticker, periodInterval: period }
    );

    if (cached && Date.now() - cached.fetchedAt < CACHE_TTL_MS) {
      return cached.candles;
    }

    // 2. Fetch from Kalshi
    const candles = await fetchFromKalshi(args.ticker, period, startTs, endTs);

    // 3. Cache the result (even if empty, to avoid hammering the API)
    if (candles.length > 0) {
      await ctx.runMutation(internal.candlesticks.upsertCachedCandles, {
        ticker: args.ticker,
        periodInterval: period,
        candles,
        fetchedAt: Date.now(),
      });
    }

    return candles;
  },
});

// ── Kalshi API fetch ─────────────────────────────────────────────

interface KalshiCandle {
  open?: number;
  open_dollars?: string;
  high?: number;
  high_dollars?: string;
  low?: number;
  low_dollars?: string;
  close?: number;
  close_dollars?: string;
  volume?: number;
  volume_fp?: string;
  period_begin?: string;
  period_end?: string;
  t?: number;
}

interface NormalizedCandle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

function parsePrice(v: number | string | undefined): number {
  if (v === undefined || v === null) return 0;
  const n = typeof v === "string" ? parseFloat(v) : v;
  // Legacy cent values (>1.0) → normalize to 0-1
  return n > 1.0 ? n / 100 : n;
}

function parseVolume(v: number | string | undefined): number {
  if (v === undefined || v === null) return 0;
  return typeof v === "string" ? parseFloat(v) : v;
}

function normalizeCandle(raw: KalshiCandle): NormalizedCandle {
  const open = parsePrice(raw.open_dollars ?? raw.open);
  const high = parsePrice(raw.high_dollars ?? raw.high);
  const low = parsePrice(raw.low_dollars ?? raw.low);
  const close = parsePrice(raw.close_dollars ?? raw.close);
  const volume = parseVolume(raw.volume_fp ?? raw.volume);

  let time: number;
  if (raw.t !== undefined) {
    time = raw.t;
  } else if (raw.period_begin) {
    time = Math.floor(new Date(raw.period_begin).getTime() / 1000);
  } else {
    time = 0;
  }

  return { time, open, high, low, close, volume };
}

async function fetchFromKalshi(
  ticker: string,
  periodInterval: number,
  startTs: number,
  endTs: number
): Promise<NormalizedCandle[]> {
  const params = new URLSearchParams({
    period_interval: String(periodInterval),
    start_ts: String(startTs),
    end_ts: String(endTs),
  });

  // Try series-based endpoint first (infer series from ticker)
  const seriesTicker = ticker.split("-")[0];
  if (seriesTicker && seriesTicker !== ticker) {
    try {
      const url = `${KALSHI_API_BASE}/series/${seriesTicker}/markets/${ticker}/candlesticks?${params}`;
      const resp = await fetch(url);
      if (resp.ok) {
        const data = await resp.json();
        const rawCandles: KalshiCandle[] = data.candlesticks ?? [];
        return rawCandles.map(normalizeCandle).filter((c) => c.time > 0);
      }
    } catch {
      // Fall through to direct endpoint
    }
  }

  // Fallback: direct market candlestick endpoint
  try {
    const url = `${KALSHI_API_BASE}/markets/${ticker}/candlesticks?${params}`;
    const resp = await fetch(url);
    if (resp.ok) {
      const data = await resp.json();
      const rawCandles: KalshiCandle[] = data.candlesticks ?? [];
      return rawCandles.map(normalizeCandle).filter((c) => c.time > 0);
    }
  } catch {
    // Both endpoints failed
  }

  return [];
}
