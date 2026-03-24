import { useState, useCallback } from "react";
import { useNexusQuery } from "@/hooks/use-nexus-query";
import type { NexusAnomaly } from "@/types/nexus";
import { MarketDataTable } from "./marketdatatable";
import { anomalyColumns } from "./anomalytablecolumns";
import { AnomalyDetailDialog } from "./AnomalyDetailDialog";
import { getSeverityStyle, getSeverityLabel, getAnomalyTypeInfo } from "./anomalytablecolumns";
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

function parseMetadata(metadata: string): Record<string, unknown> | null {
  try {
    return JSON.parse(metadata);
  } catch {
    return null;
  }
}

/** Inline detail popover content for a single anomaly. */
function AnomalyPopoverContent({ anomaly }: { anomaly: NexusAnomaly }) {
  const info = getAnomalyTypeInfo(anomaly.anomalyType);
  const Icon = info.icon;
  const parsed = parseMetadata(anomaly.metadata);

  return (
    <div className="space-y-3 max-w-sm">
      {/* Header: severity + type */}
      <div className="flex items-center justify-between gap-2">
        <span className={`px-2 py-1 rounded border-2 border-black text-xs font-bold shadow-[2px_2px_0px_0px_#000] ${getSeverityStyle(anomaly.severity)}`}>
          {getSeverityLabel(anomaly.severity)} — {anomaly.severity.toFixed(2)}
        </span>
        <span className="inline-flex items-center gap-1 px-2 py-1 rounded border border-black text-xs font-bold bg-purple-300 text-purple-800 dark:bg-purple-700 dark:text-purple-200">
          <Icon className="h-3 w-3" />
          {info.label}
        </span>
      </div>

      {/* Type description */}
      <p className="text-xs text-gray-500 dark:text-gray-400 italic">
        {info.description}
      </p>

      {/* Catalyst narrative (if available) or plain summary */}
      {anomaly.catalyst ? (
        <div className="space-y-1">
          <p className="text-sm text-gray-800 dark:text-gray-200 font-semibold">
            {anomaly.catalyst.headline}
          </p>
          <p className="text-xs text-gray-600 dark:text-gray-400">
            {anomaly.catalyst.narrative}
          </p>
          {anomaly.catalyst.signals.length > 0 && (
            <div className="flex flex-wrap gap-1 pt-1">
              {anomaly.catalyst.signals.map((signal, i) => (
                <span key={i} className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-blue-100 dark:bg-blue-800 text-blue-700 dark:text-blue-200 border border-blue-300 dark:border-blue-600">
                  {signal}
                </span>
              ))}
            </div>
          )}
        </div>
      ) : (
        <p className="text-sm text-gray-800 dark:text-gray-200 font-medium">
          {anomaly.summary}
        </p>
      )}

      {/* Details grid */}
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <span className="font-bold text-gray-500 dark:text-gray-400 uppercase block">Markets</span>
          <span className="font-bold text-gray-900 dark:text-white">{anomaly.marketCount}</span>
        </div>
        <div>
          <span className="font-bold text-gray-500 dark:text-gray-400 uppercase block">Detected</span>
          <span className="text-gray-700 dark:text-gray-300">
            {new Date(anomaly.detectedAt).toLocaleString()}
          </span>
        </div>
      </div>

      {/* Raw metadata fallback (only when no catalyst) */}
      {!anomaly.catalyst && parsed && (
        <div className="pt-2 border-t border-gray-200 dark:border-gray-600">
          <span className="text-xs font-bold text-gray-500 dark:text-gray-400 uppercase block mb-1">Details</span>
          <pre className="text-xs bg-gray-100 dark:bg-gray-700 p-2 rounded border border-black overflow-x-auto max-h-28 dark:text-gray-300">
            {JSON.stringify(parsed, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

export function AnomalyFeedView() {
  const [minSeverity, setMinSeverity] = useState<number | undefined>(undefined);
  const [anomalyType, setAnomalyType] = useState<string | undefined>(undefined);
  const [detailOpen, setDetailOpen] = useState(false);
  const [selectedAnomalies, setSelectedAnomalies] = useState<NexusAnomaly[]>([]);
  const [activeAnomaly, setActiveAnomaly] = useState<NexusAnomaly | null>(null);

  const { data: anomalies } = useNexusQuery<NexusAnomaly[]>(
    "/api/v1/anomalies",
    {
      min_severity: minSeverity,
      anomaly_type: anomalyType,
      limit: 100,
    },
  );

  // Add _id for MarketDataTable row identity
  const anomalyData = (anomalies || []).map((a) => ({ ...a, _id: String(a.anomalyId) }));

  const handleRowClick = useCallback((row: NexusAnomaly) => {
    setActiveAnomaly((prev) => (prev?.anomalyId === row.anomalyId ? null : row));
  }, []);

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

      {/* Active anomaly detail popover (shown when a row is clicked) */}
      {activeAnomaly && (
        <div className="bg-white border-4 border-black shadow-[8px_8px_0px_0px_#000] rounded-lg p-4 dark:bg-gray-800 dark:border-black dark:shadow-[8px_8px_0px_0px_#000] relative">
          <button
            onClick={() => setActiveAnomaly(null)}
            className="absolute top-3 right-3 p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
            aria-label="Close detail"
          >
            <X className="h-4 w-4 text-gray-500" />
          </button>
          <AnomalyPopoverContent anomaly={activeAnomaly} />
        </div>
      )}

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
          onRowClick={handleRowClick}
          tabletHiddenColumns={["summary", "detectedAt"]}
          renderCard={(anomaly, isSelected, toggleSelected) => {
            const info = getAnomalyTypeInfo(anomaly.anomalyType);
            const Icon = info.icon;
            const isActive = activeAnomaly?.anomalyId === anomaly.anomalyId;

            return (
              <div
                className={`border-2 border-black rounded-lg p-4 shadow-[4px_4px_0px_0px_#000] transition-colors cursor-pointer ${
                  isActive
                    ? "ring-2 ring-blue-500 bg-blue-50 dark:bg-blue-950/30"
                    : isSelected
                    ? "bg-yellow-100 dark:bg-yellow-900/30"
                    : "bg-white dark:bg-gray-700"
                }`}
                onClick={() => handleRowClick(anomaly)}
              >
                <div className="flex items-start gap-3">
                  <Checkbox
                    checked={isSelected}
                    onCheckedChange={toggleSelected}
                    aria-label="Select anomaly"
                    className="border-black shadow-[2px_2px_0px_0px_#000] mt-0.5"
                    onClick={(e: React.MouseEvent) => e.stopPropagation()}
                  />
                  <div className="flex-1 min-w-0">
                    {/* Top row: type badge + severity */}
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-black text-xs font-bold bg-purple-300 text-purple-800 dark:bg-purple-700 dark:text-purple-200">
                        <Icon className="h-3 w-3" />
                        {info.label}
                      </span>
                      <span className={`px-2 py-0.5 rounded border-2 border-black text-xs font-bold flex-shrink-0 shadow-[2px_2px_0px_0px_#000] ${getSeverityStyle(anomaly.severity)}`}>
                        {getSeverityLabel(anomaly.severity)} {anomaly.severity.toFixed(2)}
                      </span>
                    </div>

                    {/* Summary */}
                    <p className="text-sm text-gray-700 dark:text-gray-300 line-clamp-2 mb-2">
                      {anomaly.summary}
                    </p>

                    {/* Bottom row: timestamp */}
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-500 dark:text-gray-400 italic">
                        {info.description}
                      </span>
                      <span className="text-xs text-gray-400 dark:text-gray-500 ml-auto whitespace-nowrap">
                        {new Date(anomaly.detectedAt).toLocaleDateString()}
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
