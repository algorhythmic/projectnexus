/**
 * Convex schema additions for Nexus sync targets (Phase 4).
 *
 * Add these table definitions to MarketFinder's convex/schema.ts
 * alongside the existing tables.
 */
import { defineTable } from "convex/server";
import { v } from "convex/values";

// Add to schema definition:

export const nexusSyncTables = {
  // Current market state — synced every 30s from v_current_market_state
  nexusMarkets: defineTable({
    marketId: v.number(), // Nexus internal market ID
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
    .index("by_nexus_id", ["marketId"])
    .index("by_platform", ["platform"])
    .index("by_active", ["isActive"])
    .searchIndex("search_nexus_markets", {
      searchField: "title",
      filterFields: ["platform", "category", "isActive"],
    }),

  // Active anomalies — synced event-driven from v_active_anomalies
  activeAnomalies: defineTable({
    anomalyId: v.number(), // Nexus anomaly ID
    anomalyType: v.string(), // single_market, cluster, cross_platform
    severity: v.number(), // 0.0-1.0
    marketCount: v.number(),
    detectedAt: v.number(), // Unix ms
    summary: v.string(),
    metadata: v.string(), // JSON string
    clusterName: v.string(),
    syncedAt: v.number(),
  })
    .index("by_anomaly_id", ["anomalyId"])
    .index("by_severity", ["severity"])
    .index("by_detected_at", ["detectedAt"])
    .index("by_type", ["anomalyType"]),

  // Trending topics — synced every 5min from v_trending_topics
  trendingTopics: defineTable({
    clusterId: v.number(), // Nexus cluster ID
    name: v.string(),
    description: v.string(),
    marketCount: v.number(),
    anomalyCount: v.number(),
    maxSeverity: v.number(),
    syncedAt: v.number(),
  })
    .index("by_cluster_id", ["clusterId"])
    .index("by_anomaly_count", ["anomalyCount"]),

  // Market summaries — synced every 2min from v_market_summaries
  marketSummaries: defineTable({
    marketId: v.number(), // Nexus market ID
    platform: v.string(),
    title: v.string(),
    category: v.string(),
    eventCount: v.number(),
    firstEventTs: v.optional(v.union(v.number(), v.null())),
    lastEventTs: v.optional(v.union(v.number(), v.null())),
    syncedAt: v.number(),
  })
    .index("by_market_id", ["marketId"])
    .index("by_platform", ["platform"]),
};
