import { useState, useMemo, useCallback } from "react";
import { useNexusQuery } from "@/hooks/use-nexus-query";
import type { NexusMarket, MarketsResponse } from "@/types/nexus";
import { MarketDataTable } from "./marketdatatable";
import { columns, groupMarkets, getEventKey, type MarketRow } from "./markettablecolumns";
import { MarketComparisonDialog } from "./MarketComparisonDialog";
import { MarketDetailDialog } from "./MarketDetailDialog";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { GitCompareArrows, X, ChevronRight, ChevronDown } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { useDebounce } from "@/hooks/use-debounce";

export function MarketsView() {
  const [selectedPlatform, setSelectedPlatform] = useState<string | undefined>(undefined);
  const [searchTerm, setSearchTerm] = useState("");
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const [selectedMarkets, setSelectedMarkets] = useState<NexusMarket[]>([]);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [detailMarket, setDetailMarket] = useState<NexusMarket | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [limit, setLimit] = useState(500);

  const debouncedSearchTerm = useDebounce(searchTerm, 300);

  const { data: response, isLoading } = useNexusQuery<MarketsResponse>(
    "/api/v1/markets",
    {
      platform: selectedPlatform,
      search: debouncedSearchTerm || undefined,
      limit,
      sort: "rank_score",
    },
  );

  const marketData: NexusMarket[] = response?.markets ?? [];
  const canLoadMore = response ? response.total > response.offset + response.limit : false;

  // Group multi-outcome markets by event ticker prefix
  const groupedData = useMemo(
    () => groupMarkets(marketData, expandedGroups),
    [marketData, expandedGroups],
  );

  const handleRowClick = useCallback((row: MarketRow) => {
    // Toggle group expand/collapse when clicking a group header row
    if ((row._groupSize ?? 0) > 1 && !row._isChild) {
      const key = row._eventKey ?? getEventKey(row.externalId);
      setExpandedGroups((prev) => {
        const next = new Set(prev);
        if (next.has(key)) {
          next.delete(key);
        } else {
          next.add(key);
        }
        return next;
      });
    } else {
      // Single market or child outcome — open detail dialog
      setDetailMarket(row);
      setDetailOpen(true);
    }
  }, []);

  return (
    <div className="container mx-auto py-6 space-y-6">
      <div className="bg-white border-4 border-black shadow-[8px_8px_0px_0px_#000] p-6 rounded-lg dark:bg-gray-800 dark:border-black dark:shadow-[8px_8px_0px_0px_#000]">
        <h1 className="text-2xl font-bold dark:text-white">Browse prediction markets across all platforms</h1>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Search */}
        <div className="space-y-2">
          <Label className="dark:text-neutral-300">Search</Label>
          <Input
            placeholder="Search markets..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full border-2 border-black rounded-md px-2 sm:px-3 py-1.5 sm:py-2 text-xs sm:text-sm font-medium shadow-[4px_4px_0px_0px_#000] focus:ring-2 focus:ring-blue-500 focus:border-blue-500 dark:bg-neutral-800 dark:text-neutral-50 dark:placeholder-neutral-400 dark:border-black dark:shadow-[4px_4px_0px_0px_#000]"
          />
        </div>

        {/* Platform */}
        <div className="space-y-2">
          <Label className="dark:text-neutral-300">Platform</Label>
          <Select
            value={selectedPlatform || "all-platforms"}
            onValueChange={(value) =>
              setSelectedPlatform(value === "all-platforms" ? undefined : value)
            }
          >
            <SelectTrigger className="w-full border-2 border-black rounded-md px-3 py-2 text-sm shadow-[4px_4px_0px_0px_#000] focus:ring-2 focus:ring-offset-0 focus:ring-blue-500 focus:border-blue-500 dark:bg-neutral-800 dark:text-neutral-50 dark:border-black dark:shadow-[4px_4px_0px_0px_#000]">
              <SelectValue placeholder="Select a platform" />
            </SelectTrigger>
            <SelectContent className="dark:bg-neutral-900 dark:border-black dark:text-neutral-200">
              <SelectItem value="all-platforms">All Platforms</SelectItem>
              <SelectItem value="kalshi">Kalshi</SelectItem>
              <SelectItem value="polymarket">Polymarket</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Loading State */}
      {isLoading && marketData.length === 0 && (
        <div className="flex flex-col items-center justify-center py-12 space-y-4">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 dark:border-white"></div>
          <div className="text-center">
            <h3 className="text-lg font-semibold dark:text-white">Loading Markets...</h3>
            <p className="text-sm text-gray-600 dark:text-gray-400">Please wait a moment while we load market data.</p>
          </div>
        </div>
      )}

      {/* Market Data Table */}
      {marketData.length > 0 && (
        <MarketDataTable
          columns={columns}
          data={groupedData}
          onRowClick={handleRowClick}
          onLoadMore={canLoadMore ? () => setLimit((prev) => prev + 500) : undefined}
          loadMoreStatus={canLoadMore ? "CanLoadMore" : "Exhausted"}
          tabletHiddenColumns={["lastPrice", "category", "healthScore", "endDate", "syncedAt", "actions"]}
          renderCard={(market, isSelected, toggleSelected) => {
            const isGroup = (market._groupSize ?? 0) > 1;
            const isChild = market._isChild;

            // Group header card
            if (isGroup) {
              return (
                <div
                  className="border-2 border-black rounded-lg p-4 shadow-[4px_4px_0px_0px_#000] bg-gray-50 dark:bg-gray-700 cursor-pointer transition-colors hover:bg-yellow-100 dark:hover:bg-yellow-900/30"
                  onClick={() => handleRowClick(market)}
                >
                  <div className="flex items-start gap-3">
                    <Checkbox
                      checked={isSelected}
                      onCheckedChange={toggleSelected}
                      aria-label="Select market"
                      className="border-black shadow-[2px_2px_0px_0px_#000] mt-0.5"
                      onClick={(e: React.MouseEvent) => e.stopPropagation()}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-2">
                        {market._isExpanded ? (
                          <ChevronDown className="h-4 w-4 text-gray-500 shrink-0" />
                        ) : (
                          <ChevronRight className="h-4 w-4 text-gray-500 shrink-0" />
                        )}
                        <p className="font-bold text-gray-900 dark:text-white text-sm line-clamp-2">
                          {market._groupTitle || market.title}
                        </p>
                      </div>
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className={`px-2 py-0.5 rounded border border-black text-xs font-bold ${
                          market.platform === "kalshi"
                            ? "bg-blue-300 text-blue-800 dark:bg-blue-700 dark:text-blue-200"
                            : "bg-green-300 text-green-800 dark:bg-green-700 dark:text-green-200"
                        }`}>
                          {market.platform.charAt(0).toUpperCase() + market.platform.slice(1)}
                        </span>
                        <span className="px-1.5 py-0.5 text-xs font-bold bg-blue-200 text-blue-800 dark:bg-blue-700 dark:text-blue-200 border border-black rounded">
                          {market._groupSize} outcomes
                        </span>
                        <span className="px-2 py-0.5 rounded border border-black text-xs font-bold bg-gray-200 text-gray-700 dark:bg-gray-600 dark:text-gray-300">
                          {market.category}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              );
            }

            // Child outcome card (indented)
            if (isChild) {
              return (
                <div className="ml-6 border-l-2 border-blue-300 dark:border-blue-600 pl-3">
                  <div
                    className={`border border-gray-300 dark:border-gray-600 rounded-lg p-3 transition-colors ${
                      isSelected
                        ? "bg-yellow-100 dark:bg-yellow-900/30"
                        : "bg-blue-50/50 dark:bg-blue-950/20"
                    }`}
                  >
                    <div className="flex items-start gap-3">
                      <Checkbox
                        checked={isSelected}
                        onCheckedChange={toggleSelected}
                        aria-label="Select market"
                        className="border-black shadow-[2px_2px_0px_0px_#000] mt-0.5"
                      />
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-gray-700 dark:text-gray-300 text-sm line-clamp-2 mb-1">
                          {market.title}
                        </p>
                        {market.lastPrice != null ? (
                          <div className="flex items-center gap-2">
                            <span className="inline-flex items-center gap-1">
                              <span className="text-[10px] font-bold text-emerald-700 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-900/40 px-1 rounded">YES</span>
                              <span className="font-bold text-gray-900 dark:text-white">${market.lastPrice.toFixed(2)}</span>
                            </span>
                            <span className="inline-flex items-center gap-1">
                              <span className="text-[10px] font-bold text-red-700 dark:text-red-400 bg-red-100 dark:bg-red-900/40 px-1 rounded">NO</span>
                              <span className="font-bold text-gray-500 dark:text-gray-400">${(1 - market.lastPrice).toFixed(2)}</span>
                            </span>
                          </div>
                        ) : (
                          <span className="text-base font-bold text-gray-400 dark:text-gray-500">N/A</span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            }

            // Normal single-market card
            return (
              <div
                className={`border-2 border-black rounded-lg p-4 shadow-[4px_4px_0px_0px_#000] transition-colors ${
                  isSelected
                    ? "bg-yellow-100 dark:bg-yellow-900/30"
                    : "bg-white dark:bg-gray-700"
                }`}
              >
                <div className="flex items-start gap-3">
                  <Checkbox
                    checked={isSelected}
                    onCheckedChange={toggleSelected}
                    aria-label="Select market"
                    className="border-black shadow-[2px_2px_0px_0px_#000] mt-0.5"
                  />
                  <div className="flex-1 min-w-0">
                    <p className="font-bold text-gray-900 dark:text-white text-sm line-clamp-2 mb-2">
                      {market.title}
                    </p>
                    <div className="flex items-center gap-2 flex-wrap mb-2">
                      <span className={`px-2 py-0.5 rounded border border-black text-xs font-bold ${
                        market.platform === "kalshi"
                          ? "bg-blue-300 text-blue-800 dark:bg-blue-700 dark:text-blue-200"
                          : "bg-green-300 text-green-800 dark:bg-green-700 dark:text-green-200"
                      }`}>
                        {market.platform.charAt(0).toUpperCase() + market.platform.slice(1)}
                      </span>
                      <span className="px-2 py-0.5 rounded border border-black text-xs font-bold bg-gray-200 text-gray-700 dark:bg-gray-600 dark:text-gray-300">
                        {market.category}
                      </span>
                    </div>
                    <div className="flex items-center justify-between">
                      {market.lastPrice != null ? (
                        <div className="flex items-center gap-2">
                          <span className="inline-flex items-center gap-1">
                            <span className="text-[10px] font-bold text-emerald-700 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-900/40 px-1 rounded">YES</span>
                            <span className="text-base font-bold text-gray-900 dark:text-white">${market.lastPrice.toFixed(2)}</span>
                          </span>
                          <span className="inline-flex items-center gap-1">
                            <span className="text-[10px] font-bold text-red-700 dark:text-red-400 bg-red-100 dark:bg-red-900/40 px-1 rounded">NO</span>
                            <span className="text-base font-bold text-gray-500 dark:text-gray-400">${(1 - market.lastPrice).toFixed(2)}</span>
                          </span>
                        </div>
                      ) : (
                        <span className="text-base font-bold text-gray-400 dark:text-gray-500">N/A</span>
                      )}
                      <span className="text-xs text-gray-500 dark:text-gray-400">
                        {new Date(market.syncedAt).toLocaleDateString()}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            );
          }}
          renderSelectionToolbar={(selectedRows, clearSelection) => (
            <div className="flex items-center justify-between bg-yellow-300 border-2 border-black rounded-lg px-4 py-3 shadow-[4px_4px_0px_0px_#000]">
              <div className="flex items-center gap-3">
                <span className="font-bold text-black text-sm">
                  {selectedRows.length} market{selectedRows.length !== 1 ? "s" : ""} selected
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={clearSelection}
                  className="h-7 px-2 bg-white hover:bg-gray-100 border-2 border-black shadow-[2px_2px_0px_0px_#000] text-black font-bold text-xs"
                >
                  <X className="h-3 w-3 mr-1" />
                  Clear
                </Button>
              </div>
              <Button
                size="sm"
                onClick={() => setComparisonOpen(true)}
                className="h-8 bg-black text-white hover:bg-gray-800 border-2 border-black shadow-[2px_2px_0px_0px_#000] font-bold text-xs"
              >
                <GitCompareArrows className="h-4 w-4 mr-1" />
                Compare ({selectedRows.length})
              </Button>
            </div>
          )}
          onSelectionChange={setSelectedMarkets}
        />
      )}

      {/* No Results State */}
      {!isLoading && marketData.length === 0 && (
        <div className="flex flex-col items-center justify-center py-12 space-y-4">
          <div className="text-center">
            <h3 className="text-lg font-semibold dark:text-white">No Markets Found</h3>
            <p className="text-sm text-gray-600 dark:text-gray-400">Try adjusting your search filters or check back later.</p>
          </div>
        </div>
      )}

      <MarketComparisonDialog
        markets={selectedMarkets}
        open={comparisonOpen}
        onOpenChange={setComparisonOpen}
      />

      <MarketDetailDialog
        market={detailMarket}
        open={detailOpen}
        onOpenChange={setDetailOpen}
      />
    </div>
  );
}
