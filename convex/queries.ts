import { query } from "./_generated/server";
import { paginationOptsValidator } from "convex/server";
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

export const getMarketsPaginated = query({
  args: {
    platform: v.optional(v.string()),
    searchTerm: v.optional(v.string()),
    paginationOpts: paginationOptsValidator,
  },
  handler: async (ctx, args) => {
    if (args.searchTerm) {
      return await ctx.db
        .query("nexusMarkets")
        .withSearchIndex("search_nexus_markets", (q) => {
          let sq = q.search("title", args.searchTerm!);
          if (args.platform) {
            sq = sq.eq("platform", args.platform);
          }
          sq = sq.eq("isActive", true);
          return sq;
        })
        .paginate(args.paginationOpts);
    }

    if (args.platform) {
      return await ctx.db
        .query("nexusMarkets")
        .withIndex("by_platform", (q) => q.eq("platform", args.platform!))
        .order("desc")
        .paginate(args.paginationOpts);
    }

    // Order by rank_score descending — most interesting markets first
    // (high volume + near expiry = higher rank)
    return await ctx.db
      .query("nexusMarkets")
      .withIndex("by_rank")
      .order("desc")
      .paginate(args.paginationOpts);
  },
});

export const getMarketStats = query({
  args: {},
  handler: async (ctx) => {
    // Cap reads to avoid scanning 30K+ docs per reactive re-run
    // (was causing 8.71 GB/day in bandwidth).
    const SAMPLE_LIMIT = 2000;

    const kalshiSample = await ctx.db
      .query("nexusMarkets")
      .withIndex("by_platform", (q) => q.eq("platform", "kalshi"))
      .take(SAMPLE_LIMIT);

    const polymarketSample = await ctx.db
      .query("nexusMarkets")
      .withIndex("by_platform", (q) => q.eq("platform", "polymarket"))
      .take(SAMPLE_LIMIT);

    const activeSample = await ctx.db
      .query("nexusMarkets")
      .withIndex("by_active", (q) => q.eq("isActive", true))
      .take(SAMPLE_LIMIT);

    // Category distribution from a small sample
    const categoryCounts: Record<string, number> = {};
    for (const m of kalshiSample) {
      categoryCounts[m.category] = (categoryCounts[m.category] || 0) + 1;
    }

    return {
      // These are lower-bound estimates with hasMore flags
      totalMarkets: kalshiSample.length + polymarketSample.length,
      activeMarkets: activeSample.length,
      platformCounts: {
        kalshi: kalshiSample.length,
        polymarket: polymarketSample.length,
      },
      hasMore: kalshiSample.length >= SAMPLE_LIMIT,
      categoryCounts,
    };
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
