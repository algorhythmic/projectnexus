-- Migration 004: Add price tracking columns to markets table.
-- Enables v_current_market_state to read directly from markets
-- instead of aggregating from the events table via LATERAL JOINs.

ALTER TABLE markets ADD COLUMN IF NOT EXISTS yes_price DOUBLE PRECISION;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS price_updated_at BIGINT;
