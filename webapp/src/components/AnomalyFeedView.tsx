import { useQuery } from "convex/react";
import { api } from "../../../convex/_generated/api";
import { useState } from "react";
import { Doc } from "../../../convex/_generated/dataModel";
import { MarketDataTable } from "./marketdatatable";
import { anomalyColumns } from "./anomalytablecolumns";
import { AnomalyDetailDialog } from "./AnomalyDetailDialog";
import { getSeverityStyle } from "./anomalytablecolumns";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { Eye, X } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";

export function AnomalyFeedView() {
  const [minSeverity, setMinSeverity] = useState<number | undefined>(undefined);
  const [anomalyType, setAnomalyType] = useState<string | undefined>(undefined);
  const [detailOpen, setDetailOpen] = useState(false);
  const [selectedAnomalies, setSelectedAnomalies] = useState<Doc<"activeAnomalies">[]>([]);

  const anomalies = useQuery(api.queries.getActiveAnomalies, {
    minSeverity,
    anomalyType,
    limit: 100,
  });

  const anomalyData: Doc<"activeAnomalies">[] = anomalies || [];

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Header */}
      <div className="bg-white border-4 border-black shadow-[8px_8px_0px_0px_#000] p-6 rounded-lg dark:bg-gray-800 dark:border-black dark:shadow-[8px_8px_0px_0px_#000]">
        <h1 className="text-2xl font-bold dark:text-white">Active anomalies detected by Nexus across prediction markets</h1>
      </div>

      {/* Filters */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label className="dark:text-neutral-300">Severity</Label>
          <Select
            value={minSeverity !== undefined ? String(minSeverity) : "all"}
            onValueChange={(value) =>
              setMinSeverity(value === "all" ? undefined : Number(value))
            }
          >
            <SelectTrigger className="w-full border-2 border-black rounded-md px-3 py-2 text-sm shadow-[4px_4px_0px_0px_#000] dark:bg-neutral-800 dark:text-neutral-50 dark:border-black dark:shadow-[4px_4px_0px_0px_#000]">
              <SelectValue placeholder="All severities" />
            </SelectTrigger>
            <SelectContent className="dark:bg-neutral-900 dark:border-black dark:text-neutral-200">
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="0.7">High (&ge; 0.7)</SelectItem>
              <SelectItem value="0.4">Medium (&ge; 0.4)</SelectItem>
              <SelectItem value="0">Low (all)</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label className="dark:text-neutral-300">Type</Label>
          <Select
            value={anomalyType ?? "all"}
            onValueChange={(value) =>
              setAnomalyType(value === "all" ? undefined : value)
            }
          >
            <SelectTrigger className="w-full border-2 border-black rounded-md px-3 py-2 text-sm shadow-[4px_4px_0px_0px_#000] dark:bg-neutral-800 dark:text-neutral-50 dark:border-black dark:shadow-[4px_4px_0px_0px_#000]">
              <SelectValue placeholder="All types" />
            </SelectTrigger>
            <SelectContent className="dark:bg-neutral-900 dark:border-black dark:text-neutral-200">
              <SelectItem value="all">All</SelectItem>
              <SelectItem value="single_market">Single Market</SelectItem>
              <SelectItem value="cluster">Cluster</SelectItem>
              <SelectItem value="cross_platform">Cross Platform</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Loading State */}
      {anomalies === undefined && (
        <div className="flex flex-col items-center justify-center py-12 space-y-4">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 dark:border-white"></div>
          <div className="text-center">
            <h3 className="text-lg font-semibold dark:text-white">Loading Anomalies...</h3>
            <p className="text-sm text-gray-600 dark:text-gray-400">Please wait a moment while we load anomaly data.</p>
          </div>
        </div>
      )}

      {/* Anomaly Data Table */}
      {anomalies !== undefined && anomalyData.length > 0 && (
        <MarketDataTable
          columns={anomalyColumns}
          data={anomalyData}
          tabletHiddenColumns={["clusterName", "summary", "detectedAt", "actions"]}
          renderCard={(anomaly, isSelected, toggleSelected) => (
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
                  aria-label="Select anomaly"
                  className="border-black shadow-[2px_2px_0px_0px_#000] mt-0.5"
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <p className="font-bold text-gray-900 dark:text-white text-sm line-clamp-2">
                      {anomaly.clusterName}
                    </p>
                    <span className={`px-2 py-0.5 rounded border-2 border-black text-xs font-bold flex-shrink-0 shadow-[2px_2px_0px_0px_#000] ${getSeverityStyle(anomaly.severity)}`}>
                      {anomaly.severity.toFixed(2)}
                    </span>
                  </div>
                  <p className="text-sm text-gray-600 dark:text-gray-400 line-clamp-2 mb-2">
                    {anomaly.summary}
                  </p>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="px-2 py-0.5 rounded border border-black text-xs font-bold uppercase bg-purple-300 text-purple-800 dark:bg-purple-700 dark:text-purple-200">
                      {anomaly.anomalyType.replace(/_/g, " ")}
                    </span>
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      {anomaly.marketCount} market{anomaly.marketCount !== 1 ? "s" : ""}
                    </span>
                    <span className="text-xs text-gray-400 dark:text-gray-500 ml-auto">
                      {new Date(anomaly.detectedAt).toLocaleDateString()}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}
          renderSelectionToolbar={(selectedRows, clearSelection) => (
            <div className="flex items-center justify-between bg-yellow-300 border-2 border-black rounded-lg px-4 py-3 shadow-[4px_4px_0px_0px_#000]">
              <div className="flex items-center gap-3">
                <span className="font-bold text-black text-sm">
                  {selectedRows.length} anomal{selectedRows.length !== 1 ? "ies" : "y"} selected
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
                onClick={() => setDetailOpen(true)}
                className="h-8 bg-black text-white hover:bg-gray-800 border-2 border-black shadow-[2px_2px_0px_0px_#000] font-bold text-xs"
              >
                <Eye className="h-4 w-4 mr-1" />
                View Details ({selectedRows.length})
              </Button>
            </div>
          )}
          onSelectionChange={setSelectedAnomalies}
        />
      )}

      {/* No Results State */}
      {anomalies !== undefined && anomalyData.length === 0 && (
        <div className="text-center py-12 bg-white border-4 border-black rounded-lg shadow-[8px_8px_0px_0px_#000] dark:bg-gray-800 dark:border-black dark:shadow-[8px_8px_0px_0px_#000]">
          <div className="text-6xl mb-4">🔍</div>
          <h3 className="text-lg font-bold text-gray-900 mb-2 dark:text-white">No Anomalies Detected</h3>
          <p className="text-gray-500 font-medium dark:text-gray-400">
            Check back when Nexus identifies unusual market activity.
          </p>
        </div>
      )}

      <AnomalyDetailDialog
        anomalies={selectedAnomalies}
        open={detailOpen}
        onOpenChange={setDetailOpen}
      />
    </div>
  );
}
