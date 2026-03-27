-- Migration 003: Add candles table for pre-aggregated OHLCV data
-- Replaces on-the-fly compute_candlesticks() aggregation over raw events.
-- Populated by CandleAggregator from the in-memory ring buffer.

CREATE TABLE IF NOT EXISTS candles (
    id          BIGSERIAL PRIMARY KEY,
    market_id   BIGINT NOT NULL REFERENCES markets(id),
    interval    TEXT NOT NULL DEFAULT '1m',
    open_ts     BIGINT NOT NULL,
    close_ts    BIGINT NOT NULL,
    open        DOUBLE PRECISION NOT NULL,
    high        DOUBLE PRECISION NOT NULL,
    low         DOUBLE PRECISION NOT NULL,
    close       DOUBLE PRECISION NOT NULL,
    volume      BIGINT NOT NULL DEFAULT 0,
    trade_count INTEGER NOT NULL DEFAULT 0,
    created_at  BIGINT NOT NULL DEFAULT (EXTRACT(EPOCH FROM NOW()) * 1000)::BIGINT,

    UNIQUE (market_id, interval, open_ts)
);

CREATE INDEX IF NOT EXISTS idx_candles_market_interval_ts
    ON candles (market_id, interval, open_ts DESC);

CREATE INDEX IF NOT EXISTS idx_candles_open_ts
    ON candles (open_ts DESC);

CREATE INDEX IF NOT EXISTS idx_candles_created_at
    ON candles (created_at);
