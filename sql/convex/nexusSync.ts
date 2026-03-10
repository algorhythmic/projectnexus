/**
 * Convex mutations for Nexus sync layer (Phase 4, Milestone 4.1).
 *
 * Deploy this file to the MarketFinder Convex backend alongside
 * the schema additions in nexusSyncSchema.ts.
 *
 * These mutations are called by Nexus's SyncLayer to push
 * precomputed data from PostgreSQL materialized views into Convex.
 * All operations are idempotent (upsert by unique key).
 */
import { internalMutation } from "./_generated/server";
import { v } from "convex/values";

// ----------------------------------------------------------------
// Markets — from v_current_market_state (every 30s)
// ----------------------------------------------------------------

export const upsertMarkets = internalMutation({
  args: {
    markets: v.array(
      v.object({
        marketId: v.number(),
        platform: v.string(),
        externalId: v.string(),
        title: v.string(),
        category: v.string(),
        isActive: v.boolean(),
        lastPrice: v.optional(v.union(v.number(), v.null())),
        lastPriceTs: v.optional(v.union(v.number(), v.null())),
        lastVolume: v.optional(v.union(v.number(), v.null())),
        lastVolumeTs: v.optional(v.union(v.number(), v.null())),
        syncedAt: v.number(),
      })
    ),
  },
  handler: async (ctx, { markets }) => {
    let upserted = 0;
    for (const market of markets) {
      const existing = await ctx.db
        .query("nexusMarkets")
        .withIndex("by_nexus_id", (q) => q.eq("marketId", market.marketId))
        .first();

      if (existing) {
        await ctx.db.patch(existing._id, market);
      } else {
        await ctx.db.insert("nexusMarkets", market);
      }
      upserted++;
    }
    return { upserted };
  },
});

// ----------------------------------------------------------------
// Active Anomalies — from v_active_anomalies (event-driven)
// ----------------------------------------------------------------

export const upsertAnomalies = internalMutation({
  args: {
    anomalies: v.array(
      v.object({
        anomalyId: v.number(),
        anomalyType: v.string(),
        severity: v.number(),
        marketCount: v.number(),
        detectedAt: v.number(),
        summary: v.string(),
        metadata: v.string(),
        clusterName: v.string(),
        syncedAt: v.number(),
      })
    ),
  },
  handler: async (ctx, { anomalies }) => {
    // Clear stale anomalies not in the new set
    const existingAll = await ctx.db.query("activeAnomalies").collect();
    const newIds = new Set(anomalies.map((a) => a.anomalyId));
    for (const existing of existingAll) {
      if (!newIds.has(existing.anomalyId)) {
        await ctx.db.delete(existing._id);
      }
    }

    // Upsert current anomalies
    let upserted = 0;
    for (const anomaly of anomalies) {
      const existing = await ctx.db
        .query("activeAnomalies")
        .withIndex("by_anomaly_id", (q) =>
          q.eq("anomalyId", anomaly.anomalyId)
        )
        .first();

      if (existing) {
        await ctx.db.patch(existing._id, anomaly);
      } else {
        await ctx.db.insert("activeAnomalies", anomaly);
      }
      upserted++;
    }
    return { upserted };
  },
});

// ----------------------------------------------------------------
// Trending Topics — from v_trending_topics (every 5min)
// ----------------------------------------------------------------

export const upsertTrendingTopics = internalMutation({
  args: {
    topics: v.array(
      v.object({
        clusterId: v.number(),
        name: v.string(),
        description: v.string(),
        marketCount: v.number(),
        anomalyCount: v.number(),
        maxSeverity: v.number(),
        syncedAt: v.number(),
      })
    ),
  },
  handler: async (ctx, { topics }) => {
    // Replace all — clear and reinsert for consistency
    const existing = await ctx.db.query("trendingTopics").collect();
    for (const doc of existing) {
      await ctx.db.delete(doc._id);
    }
    for (const topic of topics) {
      await ctx.db.insert("trendingTopics", topic);
    }
    return { inserted: topics.length };
  },
});

// ----------------------------------------------------------------
// Market Summaries — from v_market_summaries (every 2min)
// ----------------------------------------------------------------

export const upsertMarketSummaries = internalMutation({
  args: {
    summaries: v.array(
      v.object({
        marketId: v.number(),
        platform: v.string(),
        title: v.string(),
        category: v.string(),
        eventCount: v.number(),
        firstEventTs: v.optional(v.union(v.number(), v.null())),
        lastEventTs: v.optional(v.union(v.number(), v.null())),
        syncedAt: v.number(),
      })
    ),
  },
  handler: async (ctx, { summaries }) => {
    let upserted = 0;
    for (const summary of summaries) {
      const existing = await ctx.db
        .query("marketSummaries")
        .withIndex("by_market_id", (q) =>
          q.eq("marketId", summary.marketId)
        )
        .first();

      if (existing) {
        await ctx.db.patch(existing._id, summary);
      } else {
        await ctx.db.insert("marketSummaries", summary);
      }
      upserted++;
    }
    return { upserted };
  },
});
