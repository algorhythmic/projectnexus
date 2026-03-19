import { query, mutation } from "./_generated/server";
import { v } from "convex/values";
import { getAuthUserId } from "@convex-dev/auth/server";

export const getUnreadAlertCount = query({
  args: {},
  handler: async (ctx) => {
    const userId = await getAuthUserId(ctx);
    if (!userId) return 0;

    const unread = await ctx.db
      .query("alerts")
      .withIndex("by_unread", (q) => q.eq("userId", userId).eq("isRead", false))
      .collect();
    return unread.length;
  },
});

export const getUserAlerts = query({
  args: { limit: v.optional(v.number()) },
  handler: async (ctx, args) => {
    const userId = await getAuthUserId(ctx);
    if (!userId) return [];

    return await ctx.db
      .query("alerts")
      .withIndex("by_user", (q) => q.eq("userId", userId))
      .order("desc")
      .take(args.limit || 50);
  },
});

export const markAlertsRead = mutation({
  args: { alertIds: v.array(v.id("alerts")) },
  handler: async (ctx, args) => {
    const userId = await getAuthUserId(ctx);
    if (!userId) throw new Error("Authentication required");

    for (const alertId of args.alertIds) {
      const alert = await ctx.db.get(alertId);
      if (alert && alert.userId === userId) {
        await ctx.db.patch(alertId, { isRead: true });
      }
    }
  },
});

export const updatePreferences = mutation({
  args: {
    preferences: v.object({
      categories: v.optional(v.array(v.string())),
      platforms: v.optional(v.array(v.string())),
      alertsEnabled: v.optional(v.boolean()),
      emailNotifications: v.optional(v.boolean()),
    }),
  },
  handler: async (ctx, args) => {
    const userId = await getAuthUserId(ctx);
    if (!userId) throw new Error("Authentication required");

    const user = await ctx.db.get(userId);
    if (!user) throw new Error("User not found");

    const currentPrefs = user.preferences ?? {
      categories: [],
      platforms: [],
      alertsEnabled: true,
      emailNotifications: false,
    };

    await ctx.db.patch(userId, {
      preferences: {
        ...currentPrefs,
        ...args.preferences,
      },
    });
  },
});
