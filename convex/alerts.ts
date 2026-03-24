/**
 * Alert creation mutations — called by the Nexus Python pipeline
 * via the Convex HTTP API (deploy key auth).
 *
 * User-facing alert queries (getUserAlerts, markAlertsRead, etc.)
 * live in convex/users.ts.
 */

import { internalMutation, internalQuery } from "./_generated/server";
import { v } from "convex/values";

/**
 * Create a single alert for a user.
 * Called by AlertCreator in Python when an anomaly matches user preferences.
 */
export const createAlert = internalMutation({
  args: {
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
  },
  handler: async (ctx, args) => {
    return await ctx.db.insert("alerts", {
      userId: args.userId,
      type: args.type,
      title: args.title,
      message: args.message,
      data: args.data,
      isRead: false,
      createdAt: Date.now(),
    });
  },
});

/**
 * Batch-create alerts for multiple users.
 * More efficient than calling createAlert in a loop from Python.
 */
export const createAlerts = internalMutation({
  args: {
    alerts: v.array(
      v.object({
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
      })
    ),
  },
  handler: async (ctx, args) => {
    const now = Date.now();
    let count = 0;
    for (const alert of args.alerts) {
      await ctx.db.insert("alerts", {
        ...alert,
        isRead: false,
        createdAt: now,
      });
      count++;
    }
    return count;
  },
});

/**
 * Get users who have alerts enabled, along with their preferences.
 * Called by AlertCreator to determine who should receive alerts.
 */
export const getAlertableUsers = internalQuery({
  args: {},
  handler: async (ctx) => {
    const allUsers = await ctx.db.query("users").collect();
    return allUsers
      .filter((u) => u.preferences?.alertsEnabled === true)
      .map((u) => ({
        userId: u._id,
        categories: u.preferences?.categories ?? [],
        platforms: u.preferences?.platforms ?? [],
      }));
  },
});
