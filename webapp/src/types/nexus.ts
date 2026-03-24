/**
 * TypeScript interfaces for the Nexus REST API responses.
 *
 * These replace Convex `Doc<"nexusMarkets">` and similar generated types
 * for broadcast data served by the REST API instead of Convex.
 */

export interface NexusMarket {
  marketId: number;
  platform: string;
  externalId: string;
  title: string;
  eventTitle?: string;
  category: string;
  endDate?: string | null;
  isActive: boolean;
  lastPrice?: number | null;
  lastPriceTs?: number | null;
  lastVolume?: number | null;
  lastVolumeTs?: number | null;
  volume?: number;
  rankScore?: number;
  healthScore?: number | null;
  syncedAt: number;
}

export interface CatalystInfo {
  headline: string;
  narrative: string;
  catalyst_type: string;
  confidence: number;
  signals: string[];
  source: "template" | "llm";
  llm_available?: boolean;
  template_headline?: string;
}

export interface NexusAnomaly {
  anomalyId: number;
  anomalyType: string;
  severity: number;
  marketCount: number;
  detectedAt: number;
  summary: string;
  metadata: string;
  clusterName: string;
  catalyst?: CatalystInfo | null;
  syncedAt: number;
}

export interface NexusTopic {
  clusterId: number;
  name: string;
  description: string;
  marketCount: number;
  anomalyCount: number;
  maxSeverity: number;
  syncedAt: number;
}

export interface MarketStats {
  totalMarkets: number;
  activeMarkets: number;
  platformCounts: Record<string, number>;
  categoryCounts: Record<string, number>;
}

export interface AnomalyStats {
  activeCount: number;
  avgSeverity: number;
  bySeverityBucket: {
    high: number;
    medium: number;
    low: number;
  };
}

export interface SyncStatus {
  [key: string]: {
    lastRefresh: number;
    recordCount: number;
  };
}

export interface MarketsResponse {
  markets: NexusMarket[];
  total: number;
  offset: number;
  limit: number;
}

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}
