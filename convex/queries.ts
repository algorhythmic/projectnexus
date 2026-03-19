import { query } from "./_generated/server";
import { v } from "convex/values";

export const getMarkets = query({
  args: {
    platform: v.optional(v.string()),
    searchTerm: v.optional(v.string()),
    count: v.optional(v.number()),
  },
  handler: async (ctx, args) => {
    const limit = args.count ?? 50;

    if (args.searchTerm) {
      let searchQuery = ctx.db
        .query("nexusMarkets")
        .withSearchIndex("search_nexus_markets", (q) => {
          let sq = q.search("title", args.searchTerm!);
          if (args.platform) {
            sq = sq.eq("platform", args.platform);
          }
          sq = sq.eq("isActive", true);
          return sq;
        });

      return await searchQuery.take(limit);
    }

    if (args.platform) {
      return await ctx.db
        .query("nexusMarkets")
        .withIndex("by_platform", (q) => q.eq("platform", args.platform!))
        .take(limit);
    }

    return await ctx.db
      .query("nexusMarkets")
      .withIndex("by_active", (q) => q.eq("isActive", true))
      .take(limit);
  },
});

export const getMarketStats = query({
  args: {},
  handler: async (ctx) => {
    // Query each platform separately with limits to stay under Convex's
    // 32k document read and 16MB byte limits per function execution.
    const PLATFORM_LIMIT = 10000;

    const kalshi = (await ctx.db
      .query("nexusMarkets")
      .withIndex("by_platform", (q) => q.eq("platform", "kalshi"))
      .take(PLATFORM_LIMIT)).length;

    const polymarket = (await ctx.db
      .query("nexusMarkets")
      .withIndex("by_platform", (q) => q.eq("platform", "polymarket"))
      .take(PLATFORM_LIMIT)).length;

    const platformCounts: Record<string, number> = { kalshi, polymarket };
    const totalMarkets = kalshi + polymarket;

    // Sample recent markets for category distribution
    const sample = await ctx.db
      .query("nexusMarkets")
      .order("desc")
      .take(500);

    const categoryCounts: Record<string, number> = {};
    for (const m of sample) {
      categoryCounts[m.category] = (categoryCounts[m.category] || 0) + 1;
    }

    return { totalMarkets, platformCounts, categoryCounts };
  },
});

export const getActiveAnomalies = query({
  args: {
    minSeverity: v.optional(v.number()),
    anomalyType: v.optional(v.string()),
    limit: v.optional(v.number()),
  },
  handler: async (ctx, args) => {
    const limit = args.limit ?? 50;

    let results;
    if (args.anomalyType) {
      results = await ctx.db
        .query("activeAnomalies")
        .withIndex("by_type", (q) => q.eq("anomalyType", args.anomalyType!))
        .collect();
    } else {
      results = await ctx.db
        .query("activeAnomalies")
        .withIndex("by_detected_at")
        .order("desc")
        .collect();
    }

    if (args.minSeverity !== undefined) {
      results = results.filter((a) => a.severity >= args.minSeverity!);
    }

    // Sort by detectedAt desc if we used a different index
    if (args.anomalyType) {
      results.sort((a, b) => b.detectedAt - a.detectedAt);
    }

    return results.slice(0, limit);
  },
});

export const getAnomalyStats = query({
  args: {},
  handler: async (ctx) => {
    const anomalies = await ctx.db.query("activeAnomalies").collect();

    const activeCount = anomalies.length;
    const avgSeverity =
      activeCount > 0
        ? anomalies.reduce((sum, a) => sum + a.severity, 0) / activeCount
        : 0;

    let high = 0;
    let medium = 0;
    let low = 0;
    for (const a of anomalies) {
      if (a.severity >= 0.7) high++;
      else if (a.severity >= 0.4) medium++;
      else low++;
    }

    return {
      activeCount,
      avgSeverity,
      bySeverityBucket: { high, medium, low },
    };
  },
});

export const getTrendingTopics = query({
  args: {
    limit: v.optional(v.number()),
  },
  handler: async (ctx, args) => {
    const limit = args.limit ?? 20;

    const topics = await ctx.db
      .query("trendingTopics")
      .withIndex("by_anomaly_count")
      .order("desc")
      .take(limit);

    return topics;
  },
});

export const getSyncStatus = query({
  args: {},
  handler: async (ctx) => {
    const latestMarket = await ctx.db
      .query("nexusMarkets")
      .order("desc")
      .first();
    const latestAnomaly = await ctx.db
      .query("activeAnomalies")
      .order("desc")
      .first();
    const latestTopic = await ctx.db
      .query("trendingTopics")
      .order("desc")
      .first();
    const latestSummary = await ctx.db
      .query("marketSummaries")
      .order("desc")
      .first();

    return {
      nexusMarkets: latestMarket?.syncedAt ?? null,
      activeAnomalies: latestAnomaly?.syncedAt ?? null,
      trendingTopics: latestTopic?.syncedAt ?? null,
      marketSummaries: latestSummary?.syncedAt ?? null,
    };
  },
});
