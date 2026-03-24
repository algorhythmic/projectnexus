import { useNexusQuery } from "@/hooks/use-nexus-query";
import type { NexusTopic } from "@/types/nexus";

function getSeverityDot(severity: number) {
  if (severity >= 0.7) return "bg-red-500";
  if (severity >= 0.4) return "bg-yellow-500";
  return "bg-blue-500";
}

function timeAgo(timestamp: number) {
  const seconds = Math.floor((Date.now() - timestamp) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function TrendingTopicsView() {
  const { data: topics } = useNexusQuery<NexusTopic[]>("/api/v1/topics", { limit: 20 });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-white border-4 border-black shadow-[8px_8px_0px_0px_#000] p-6 rounded-lg dark:bg-gray-800 dark:border-black dark:shadow-[8px_8px_0px_0px_#000]">
        <p className="text-gray-600 font-medium dark:text-gray-400">
          Topic clusters ranked by anomaly activity, detected by Nexus
        </p>
      </div>

      {/* Topics Grid */}
      {topics === undefined ? (
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-gray-900 dark:border-white"></div>
        </div>
      ) : topics.length === 0 ? (
        <div className="text-center py-12 bg-white border-4 border-black rounded-lg shadow-[8px_8px_0px_0px_#000] dark:bg-gray-800 dark:border-black dark:shadow-[8px_8px_0px_0px_#000]">
          <div className="text-6xl mb-4">📡</div>
          <h3 className="text-lg font-bold text-gray-900 mb-2 dark:text-white">No Trending Topics</h3>
          <p className="text-gray-500 font-medium dark:text-gray-400">
            Topics appear as Nexus discovers related market clusters.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {topics.map((topic) => (
            <div
              key={topic.clusterId}
              className="bg-white border-4 border-black rounded-lg p-6 shadow-[8px_8px_0px_0px_#000] hover:shadow-[4px_4px_0px_0px_#000] hover:translate-x-[4px] hover:translate-y-[4px] transition-all dark:bg-gray-800 dark:border-black dark:shadow-[8px_8px_0px_0px_#000] dark:hover:shadow-[4px_4px_0px_0px_#000]"
            >
              <div className="flex items-start justify-between mb-3">
                <h3 className="text-lg font-bold text-gray-900 dark:text-white">{topic.name}</h3>
                <div className={`w-3 h-3 rounded-full border-2 border-black flex-shrink-0 mt-1 ${getSeverityDot(topic.maxSeverity)}`} />
              </div>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-4 line-clamp-3">{topic.description}</p>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="px-2 py-1 rounded border-2 border-black text-xs font-bold bg-blue-300 text-blue-800 shadow-[2px_2px_0px_0px_#000] dark:bg-blue-700 dark:text-blue-200">
                  {topic.marketCount} markets
                </span>
                <span className={`px-2 py-1 rounded border-2 border-black text-xs font-bold shadow-[2px_2px_0px_0px_#000] ${
                  topic.anomalyCount > 0
                    ? "bg-red-300 text-red-800 dark:bg-red-700 dark:text-red-200"
                    : "bg-gray-300 text-gray-800 dark:bg-gray-600 dark:text-gray-200"
                }`}>
                  {topic.anomalyCount} anomalies
                </span>
                <span className="text-xs text-gray-500 dark:text-gray-400 ml-auto">
                  {timeAgo(topic.syncedAt)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
