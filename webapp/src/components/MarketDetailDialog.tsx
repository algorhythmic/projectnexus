/**
 * MarketDetailDialog — shows market info + candlestick chart for a single market.
 *
 * Opens when clicking a market row in MarketsView.  Fetches candlestick data
 * from the Convex caching proxy (which in turn fetches from Kalshi's public API).
 */

import { useState } from "react";
import { useAction } from "convex/react";
import { api } from "../../../convex/_generated/api";
import { Doc } from "../../../convex/_generated/dataModel";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { CandlestickChart } from "./CandlestickChart";
import { ExternalLink, BarChart3, Clock, TrendingUp, Activity } from "lucide-react";

interface MarketDetailDialogProps {
  market: Doc<"nexusMarkets"> | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

function formatPrice(price: number | null | undefined) {
  if (price == null) return "N/A";
  return `$${price.toFixed(2)} (${(price * 100).toFixed(1)}%)`;
}

function formatVolume(volume: number | null | undefined) {
  if (volume == null) return "N/A";
  return volume.toLocaleString();
}

function getPlatformUrl(platform: string, externalId: string) {
  if (platform === "kalshi") {
    return `https://kalshi.com/markets/${externalId}`;
  }
  if (platform === "polymarket") {
    return `https://polymarket.com/event/${externalId}`;
  }
  return "#";
}

function platformBadgeClass(platform: string) {
  switch (platform.toLowerCase()) {
    case "kalshi":
      return "bg-blue-300 text-blue-800 dark:bg-blue-700 dark:text-blue-200";
    case "polymarket":
      return "bg-green-300 text-green-800 dark:bg-green-700 dark:text-green-200";
    default:
      return "bg-gray-300 text-gray-800 dark:bg-gray-600 dark:text-gray-200";
  }
}

export function MarketDetailDialog({
  market,
  open,
  onOpenChange,
}: MarketDetailDialogProps) {
  const getCandlesticks = useAction(api.candlesticks.getCandlesticks);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState<string | null>(null);
  const [chartLoaded, setChartLoaded] = useState(false);

  // Fetch candlesticks when dialog opens with a new market
  const handleOpenChange = (isOpen: boolean) => {
    if (isOpen && market && !chartLoaded) {
      loadChart(market.externalId);
    }
    if (!isOpen) {
      // Reset state when closing
      setCandles([]);
      setChartLoaded(false);
      setChartError(null);
    }
    onOpenChange(isOpen);
  };

  const loadChart = async (ticker: string) => {
    setChartLoading(true);
    setChartError(null);
    try {
      const result = await getCandlesticks({ ticker, periodInterval: 60 });
      setCandles(result ?? []);
      setChartLoaded(true);
    } catch (err) {
      setChartError("Unable to load price history");
      console.error("Candlestick fetch error:", err);
    } finally {
      setChartLoading(false);
    }
  };

  if (!market) return null;

  const endDate = market.endDate
    ? new Date(market.endDate).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })
    : "—";

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-4xl w-[95vw] max-h-[90vh] overflow-y-auto p-6">
        <DialogHeader>
          <DialogTitle className="text-xl font-bold dark:text-white pr-8 leading-tight">
            {market.title}
          </DialogTitle>
          {market.eventTitle && (
            <DialogDescription className="text-sm">
              {market.eventTitle}
            </DialogDescription>
          )}
        </DialogHeader>

        {/* Market info grid */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mt-4">
          {/* Price card */}
          <div className="bg-white border-4 border-black shadow-[4px_4px_0px_0px_#000] rounded-lg p-3 dark:bg-gray-800 dark:shadow-[4px_4px_0px_0px_#1f2937]">
            <div className="flex items-center gap-1.5 mb-1">
              <TrendingUp className="h-3.5 w-3.5 text-gray-500 dark:text-gray-400" />
              <span className="text-[10px] font-bold text-gray-500 uppercase dark:text-gray-400">
                Price
              </span>
            </div>
            <div className="text-lg font-bold text-gray-900 dark:text-white">
              {market.lastPrice != null ? (
                <>
                  <span className="text-emerald-600 dark:text-emerald-400">
                    ${market.lastPrice.toFixed(2)}
                  </span>
                  <span className="text-xs text-gray-400 ml-1">YES</span>
                </>
              ) : (
                "N/A"
              )}
            </div>
          </div>

          {/* Volume card */}
          <div className="bg-white border-4 border-black shadow-[4px_4px_0px_0px_#000] rounded-lg p-3 dark:bg-gray-800 dark:shadow-[4px_4px_0px_0px_#1f2937]">
            <div className="flex items-center gap-1.5 mb-1">
              <BarChart3 className="h-3.5 w-3.5 text-gray-500 dark:text-gray-400" />
              <span className="text-[10px] font-bold text-gray-500 uppercase dark:text-gray-400">
                Volume
              </span>
            </div>
            <div className="text-lg font-bold text-gray-900 dark:text-white">
              {formatVolume(market.volume ?? market.lastVolume)}
            </div>
          </div>

          {/* Platform badge */}
          <div className="bg-white border-4 border-black shadow-[4px_4px_0px_0px_#000] rounded-lg p-3 dark:bg-gray-800 dark:shadow-[4px_4px_0px_0px_#1f2937]">
            <span className="text-[10px] font-bold text-gray-500 uppercase dark:text-gray-400 block mb-1">
              Platform
            </span>
            <span
              className={`px-2 py-0.5 rounded border border-black text-xs font-bold ${platformBadgeClass(market.platform)}`}
            >
              {market.platform.charAt(0).toUpperCase() + market.platform.slice(1)}
            </span>
          </div>

          {/* Resolves */}
          <div className="bg-white border-4 border-black shadow-[4px_4px_0px_0px_#000] rounded-lg p-3 dark:bg-gray-800 dark:shadow-[4px_4px_0px_0px_#1f2937]">
            <div className="flex items-center gap-1.5 mb-1">
              <Clock className="h-3.5 w-3.5 text-gray-500 dark:text-gray-400" />
              <span className="text-[10px] font-bold text-gray-500 uppercase dark:text-gray-400">
                Resolves
              </span>
            </div>
            <div className="text-sm font-bold text-gray-900 dark:text-white">
              {endDate}
            </div>
          </div>

          {/* Health Score */}
          <div className="bg-white border-4 border-black shadow-[4px_4px_0px_0px_#000] rounded-lg p-3 dark:bg-gray-800 dark:shadow-[4px_4px_0px_0px_#1f2937]">
            <div className="flex items-center gap-1.5 mb-1">
              <Activity className="h-3.5 w-3.5 text-gray-500 dark:text-gray-400" />
              <span className="text-[10px] font-bold text-gray-500 uppercase dark:text-gray-400">
                Health
              </span>
            </div>
            {market.healthScore != null ? (
              <div className="text-lg font-bold">
                <span
                  className={
                    market.healthScore >= 0.7
                      ? "text-red-600 dark:text-red-400"
                      : market.healthScore >= 0.4
                        ? "text-yellow-600 dark:text-yellow-400"
                        : "text-blue-600 dark:text-blue-400"
                  }
                >
                  {Math.round(market.healthScore * 100)}
                </span>
                <span className="text-xs text-gray-400 ml-1">/100</span>
              </div>
            ) : (
              <div className="text-sm text-gray-400 dark:text-gray-500">—</div>
            )}
          </div>
        </div>

        {/* Candlestick chart */}
        <div className="mt-4">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-bold text-gray-700 dark:text-gray-300 uppercase">
              Price History (1h candles, 24h)
            </h3>
            {chartLoaded && candles.length > 0 && (
              <span className="text-xs text-gray-400 dark:text-gray-500">
                {candles.length} candles
              </span>
            )}
          </div>
          <CandlestickChart
            data={candles}
            height={280}
            loading={chartLoading}
            error={chartError}
          />
        </div>

        {/* Actions */}
        <div className="flex items-center gap-3 mt-4 pt-3 border-t-2 border-gray-200 dark:border-gray-700">
          <Button
            variant="outline"
            size="sm"
            asChild
            className="border-2 border-black shadow-[2px_2px_0px_0px_#000] font-bold text-xs dark:border-gray-600 dark:shadow-[2px_2px_0px_0px_#1f2937]"
          >
            <a
              href={getPlatformUrl(market.platform, market.externalId)}
              target="_blank"
              rel="noopener noreferrer"
            >
              <ExternalLink className="h-3.5 w-3.5 mr-1.5" />
              View on {market.platform.charAt(0).toUpperCase() + market.platform.slice(1)}
            </a>
          </Button>
          <div className="flex-1" />
          <span className="text-xs text-gray-400 dark:text-gray-500">
            {market.category} &middot; {market.externalId}
          </span>
        </div>
      </DialogContent>
    </Dialog>
  );
}
