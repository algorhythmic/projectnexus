import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";
import { authTables } from "@convex-dev/auth/server";

const applicationTables = {
  // ── Nexus sync targets (populated by Nexus sync layer) ──────────

  nexusMarkets: defineTable({
    marketId: v.number(),
    platform: v.string(),
    externalId: v.string(),
    title: v.string(),
    eventTitle: v.optional(v.string()),
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

  activeAnomalies: defineTable({
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
    .index("by_anomaly_id", ["anomalyId"])
    .index("by_severity", ["severity"])
    .index("by_detected_at", ["detectedAt"])
    .index("by_type", ["anomalyType"]),

  trendingTopics: defineTable({
    clusterId: v.number(),
    name: v.string(),
    description: v.string(),
    marketCount: v.number(),
    anomalyCount: v.number(),
    maxSeverity: v.number(),
    syncedAt: v.number(),
  })
    .index("by_cluster_id", ["clusterId"])
    .index("by_anomaly_count", ["anomalyCount"]),

  marketSummaries: defineTable({
    marketId: v.number(),
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

  // ── Webapp-owned tables ─────────────────────────────────────────

  users: defineTable({
    name: v.optional(v.string()),
    email: v.optional(v.string()),
    image: v.optional(v.string()),
    isAnonymous: v.optional(v.boolean()),
    emailVerificationTime: v.optional(v.number()),
    preferences: v.optional(
      v.object({
        categories: v.array(v.string()),
        platforms: v.array(v.string()),
        alertsEnabled: v.boolean(),
        emailNotifications: v.boolean(),
      })
    ),
  }).index("email", ["email"]),

  alerts: defineTable({
    userId: v.id("users"),
    type: v.union(
      v.literal("anomaly"),
      v.literal("price_change"),
      v.literal("new_market")
    ),
    title: v.string(),
    message: v.string(),
    data: v.optional(
      v.object({
        anomalyId: v.optional(v.number()),
        marketId: v.optional(v.number()),
      })
    ),
    isRead: v.boolean(),
    createdAt: v.number(),
  })
    .index("by_user", ["userId"])
    .index("by_created_at", ["createdAt"])
    .index("by_unread", ["userId", "isRead"]),
};

export default defineSchema({
  ...authTables,
  ...applicationTables,
});
