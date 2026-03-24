import type { NexusAnomaly } from "@/types/nexus";
import { getSeverityStyle } from "./anomalytablecolumns";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";

interface AnomalyDetailDialogProps {
  anomalies: NexusAnomaly[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function parseMetadata(metadata: string): Record<string, unknown> | null {
  try {
    return JSON.parse(metadata);
  } catch {
    return null;
  }
}

export function AnomalyDetailDialog({
  anomalies,
  open,
  onOpenChange,
}: AnomalyDetailDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl w-[90vw] max-h-[80vh] overflow-y-auto p-6">
        <DialogHeader>
          <DialogTitle className="text-xl font-bold dark:text-white">
            Anomaly Details ({anomalies.length})
          </DialogTitle>
          <DialogDescription>
            Expanded view of selected anomalies
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
          {anomalies.map((anomaly) => {
            const parsed = parseMetadata(anomaly.metadata);
            return (
              <div
                key={anomaly.anomalyId}
                className="bg-white border-4 border-black shadow-[4px_4px_0px_0px_#000] rounded-lg p-4 dark:bg-gray-800 dark:shadow-[4px_4px_0px_0px_#1f2937]"
              >
                <div className="flex items-start justify-between mb-3">
                  <h4 className="font-bold text-gray-900 dark:text-white text-sm flex-1 mr-2">
                    {anomaly.clusterName}
                  </h4>
                  <span className={`px-2 py-1 rounded border-2 border-black text-xs font-bold shadow-[2px_2px_0px_0px_#000] flex-shrink-0 ${getSeverityStyle(anomaly.severity)}`}>
                    {anomaly.severity.toFixed(2)}
                  </span>
                </div>

                <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
                  {anomaly.summary}
                </p>

                {anomaly.catalyst && (
                  <div className="mb-3 p-3 bg-blue-50 dark:bg-blue-900/30 rounded border-2 border-blue-300 dark:border-blue-700">
                    <div className="flex items-center justify-between mb-1">
                      <p className="text-sm font-semibold text-blue-900 dark:text-blue-200">
                        {anomaly.catalyst.headline}
                      </p>
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${anomaly.catalyst.source === "llm" ? "bg-green-200 text-green-800 dark:bg-green-700 dark:text-green-200" : "bg-gray-200 text-gray-600 dark:bg-gray-600 dark:text-gray-300"}`}>
                        {anomaly.catalyst.source}
                      </span>
                    </div>
                    <p className="text-xs text-blue-800 dark:text-blue-300 mb-2">
                      {anomaly.catalyst.narrative}
                    </p>
                    {anomaly.catalyst.signals.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {anomaly.catalyst.signals.map((signal, i) => (
                          <span key={i} className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-blue-100 dark:bg-blue-800 text-blue-700 dark:text-blue-200 border border-blue-300 dark:border-blue-600">
                            {signal}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-gray-500 uppercase dark:text-gray-400">Type</span>
                    <span className="px-2 py-0.5 rounded border border-black text-xs font-bold uppercase bg-purple-300 text-purple-800 dark:bg-purple-700 dark:text-purple-200">
                      {anomaly.anomalyType.replace(/_/g, " ")}
                    </span>
                  </div>

                  {anomaly.catalyst && (
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-gray-500 uppercase dark:text-gray-400">Catalyst</span>
                      <span className="px-2 py-0.5 rounded border border-black text-xs font-bold uppercase bg-orange-200 text-orange-800 dark:bg-orange-700 dark:text-orange-200">
                        {anomaly.catalyst.catalyst_type} ({(anomaly.catalyst.confidence * 100).toFixed(0)}%)
                      </span>
                    </div>
                  )}

                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-gray-500 uppercase dark:text-gray-400">Markets</span>
                    <span className="font-bold text-gray-900 dark:text-white">{anomaly.marketCount}</span>
                  </div>

                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-gray-500 uppercase dark:text-gray-400">Detected</span>
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      {new Date(anomaly.detectedAt).toLocaleString()}
                    </span>
                  </div>

                  {parsed && !anomaly.catalyst && (
                    <div className="pt-2 border-t border-gray-200 dark:border-gray-600">
                      <span className="text-xs font-bold text-gray-500 uppercase dark:text-gray-400 block mb-1">Metadata</span>
                      <pre className="text-xs bg-gray-100 dark:bg-gray-700 p-2 rounded border border-black overflow-x-auto max-h-32 dark:text-gray-300">
                        {JSON.stringify(parsed, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
}
