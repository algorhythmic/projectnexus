import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";
import { authTables } from "@convex-dev/auth/server";

const applicationTables = {
  // ── Webapp-owned tables ─────────────────────────────────────────
  // Broadcast data (markets, anomalies, topics) is served by the
  // Nexus REST API — not stored in Convex.

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
