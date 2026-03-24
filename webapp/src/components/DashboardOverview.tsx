import { useNexusQuery } from "@/hooks/use-nexus-query";
import type { MarketStats, AnomalyStats, NexusAnomaly, NexusTopic, SyncStatus } from "@/types/nexus";

function formatTimeAgo(timestamp: number | null) {
  if (!timestamp) return "Never";
  const seconds = Math.floor((Date.now() - timestamp) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

interface DashboardOverviewProps {
  onViewChange: (view: string) => void;
}

export function DashboardOverview({ onViewChange }: DashboardOverviewProps) {
  const { data: marketStats } = useNexusQuery<MarketStats>("/api/v1/markets/stats");
  const { data: anomalyStats } = useNexusQuery<AnomalyStats>("/api/v1/anomalies/stats");
  const { data: recentAnomalies } = useNexusQuery<NexusAnomaly[]>("/api/v1/anomalies", { limit: 5 });
  const { data: trendingTopics } = useNexusQuery<NexusTopic[]>("/api/v1/topics", { limit: 5 });
  const { data: syncStatus } = useNexusQuery<SyncStatus>("/api/v1/status", undefined, { pollingInterval: 10_000 });

  const isLoading = marketStats === undefined || anomalyStats === undefined;

  const lastSync = syncStatus
    ? Math.max(
        ...Object.values(syncStatus).map((s) => s.lastRefresh ?? 0)
      )
    : null;

  const stats = [
    {
      title: "Markets Tracked",
      value: marketStats?.totalMarkets ?? 0,
      icon: "🎯",
      view: "markets",
    },
    {
      title: "Active Anomalies",
      value: anomalyStats?.activeCount ?? 0,
      icon: "⚠️",
      view: "anomalies",
    },
    {
      title: "Avg Severity",
      value: anomalyStats ? anomalyStats.avgSeverity.toFixed(2) : "0.00",
      icon: "📊",
      view: "anomalies",
    },
    {
      title: "Last Sync",
      value: formatTimeAgo(lastSync),
      icon: "🔄",
      view: null,
    },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-white border-4 border-black shadow-[8px_8px_0px_0px_#000] p-6 rounded-lg dark:bg-gray-800 dark:border-black dark:shadow-[8px_8px_0px_0px_#000]">
        <p className="text-gray-600 font-medium mt-1 dark:text-white">Overview of prediction market activity from Nexus</p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 md:grid-cols-2 lg:grid-cols-4 gap-4 md:gap-6">
        {stats.map((stat, index) => (
          <div
            key={index}
            className={`bg-white rounded-lg border-4 border-black p-4 md:p-6 shadow-[8px_8px_0px_0px_#000] hover:shadow-[4px_4px_0px_0px_#000] hover:translate-x-[4px] hover:translate-y-[4px] transition-all dark:bg-gray-800 dark:border-black dark:shadow-[8px_8px_0px_0px_#000] dark:hover:shadow-[4px_4px_0px_0px_#000] ${stat.view ? "cursor-pointer" : ""}`}
            onClick={stat.view ? () => onViewChange(stat.view!) : undefined}
          >
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-bold text-gray-600 uppercase tracking-wider dark:text-gray-400">{stat.title}</p>
                <p className="text-2xl font-bold text-gray-900 mt-1 dark:text-white">
                  {isLoading ? "..." : stat.value}
                </p>
              </div>
              <div className="text-2xl">{stat.icon}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Recent Anomalies + Trending Topics */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Anomalies */}
        <div className="bg-white rounded-lg border-4 border-black p-6 shadow-[8px_8px_0px_0px_#000] dark:bg-gray-800 dark:border-black dark:shadow-[8px_8px_0px_0px_#000]">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-bold text-gray-900 flex items-center gap-2 dark:text-white">
              ⚠️ <span>Recent Anomalies</span>
            </h3>
            <button
              onClick={() => onViewChange("anomalies")}
              className="text-sm font-bold text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300"
            >
              View all →
            </button>
          </div>
          {recentAnomalies === undefined ? (
            <div className="text-center py-8">
              <p className="text-gray-500 font-medium dark:text-gray-400">Loading...</p>
            </div>
          ) : recentAnomalies.length > 0 ? (
            <div className="space-y-3">
              {recentAnomalies.map((anomaly) => (
                <div
                  key={anomaly.anomalyId}
                  className="flex items-center justify-between p-4 bg-gray-50 rounded-lg border-2 border-black shadow-[4px_4px_0px_0px_#000] dark:bg-gray-700 dark:border-black dark:shadow-[4px_4px_0px_0px_#000] cursor-pointer hover:bg-yellow-50 hover:shadow-[2px_2px_0px_0px_#000] hover:translate-x-[2px] hover:translate-y-[2px] transition-all dark:hover:bg-gray-600"
                  onClick={() => onViewChange("anomalies")}
                >
                  <div className="flex-1 min-w-0">
                    <p className="font-bold text-gray-900 dark:text-white truncate">{anomaly.clusterName}</p>
                    <p className="text-sm text-gray-600 font-medium dark:text-gray-400 truncate">
                      {anomaly.summary}
                    </p>
                  </div>
                  <div className="text-right ml-4 flex-shrink-0">
                    <span className={`px-2 py-1 rounded border-2 border-black text-xs font-bold ${
                      anomaly.severity >= 0.7 ? "bg-red-300 text-red-800" :
                      anomaly.severity >= 0.4 ? "bg-yellow-300 text-yellow-800" :
                      "bg-blue-300 text-blue-800"
                    }`}>
                      {anomaly.severity.toFixed(2)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8">
              <div className="text-4xl mb-2">✅</div>
              <p className="text-gray-500 font-medium dark:text-gray-400">No anomalies detected</p>
            </div>
          )}
        </div>

        {/* Trending Topics */}
        <div className="bg-white rounded-lg border-4 border-black p-6 shadow-[8px_8px_0px_0px_#000] dark:bg-gray-800 dark:border-black dark:shadow-[8px_8px_0px_0px_#000]">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-bold text-gray-900 flex items-center gap-2 dark:text-white">
              🔥 <span>Trending Topics</span>
            </h3>
            <button
              onClick={() => onViewChange("topics")}
              className="text-sm font-bold text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300"
            >
              View all →
            </button>
          </div>
          {trendingTopics === undefined ? (
            <div className="text-center py-8">
              <p className="text-gray-500 font-medium dark:text-gray-400">Loading...</p>
            </div>
          ) : trendingTopics.length > 0 ? (
            <div className="space-y-3">
              {trendingTopics.map((topic, index) => (
                <div
                  key={topic.clusterId}
                  className="flex items-start space-x-3 p-3 bg-gray-50 rounded border-2 border-black dark:bg-gray-700 dark:border-black cursor-pointer hover:bg-yellow-50 hover:shadow-[2px_2px_0px_0px_#000] hover:translate-x-[2px] hover:translate-y-[2px] transition-all dark:hover:bg-gray-600"
                  onClick={() => onViewChange("topics")}
                >
                  <span className="text-sm font-bold text-gray-700 mt-1 bg-yellow-300 px-2 py-1 rounded border border-black dark:text-gray-900 dark:bg-yellow-400 dark:border-black">#{index + 1}</span>
                  <div className="flex-1 min-w-0">
                    <p className="font-bold text-gray-900 truncate dark:text-white">{topic.name}</p>
                    <p className="text-sm text-gray-600 font-medium dark:text-gray-400">{topic.marketCount} markets</p>
                  </div>
                  <div className="text-right">
                    <span className={`px-2 py-1 rounded border border-black text-xs font-bold ${
                      topic.anomalyCount > 0 ? "bg-red-300 text-red-800" : "bg-gray-200 text-gray-600"
                    }`}>
                      {topic.anomalyCount} anomalies
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8">
              <div className="text-4xl mb-2">📡</div>
              <p className="text-gray-500 font-medium dark:text-gray-400">No topics detected yet</p>
            </div>
          )}
        </div>
      </div>

      {/* Sync Status */}
      <div className="bg-white rounded-lg border-4 border-black p-6 shadow-[8px_8px_0px_0px_#000] dark:bg-gray-800 dark:border-black dark:shadow-[8px_8px_0px_0px_#000]">
        <h3 className="text-lg font-bold text-gray-900 mb-4 flex items-center gap-2 dark:text-white">
          🔗 <span>Sync Status</span>
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {syncStatus ? (
            <>
              {([
                { name: "Markets", key: "markets" },
                { name: "Anomalies", key: "anomalies" },
                { name: "Topics", key: "topics" },
                { name: "Summaries", key: "summaries" },
              ] as const).map((table) => {
                const entry = syncStatus[table.key];
                return (
                  <div key={table.key} className="flex items-center space-x-3 p-4 bg-gray-50 rounded-lg border-2 border-black shadow-[2px_2px_0px_0px_#000] dark:bg-gray-700 dark:border-black dark:shadow-[2px_2px_0px_0px_#000]">
                    <div className={`w-4 h-4 rounded-full border-2 border-black ${
                      entry ? "bg-green-400" : "bg-gray-400"
                    }`} />
                    <div className="flex-1">
                      <p className="font-bold text-gray-900 dark:text-white">{table.name}</p>
                      <p className="text-xs text-gray-500 font-medium dark:text-gray-400">
                        {entry
                          ? `Last sync: ${formatTimeAgo(entry.lastRefresh)}`
                          : "Never synced"}
                      </p>
                    </div>
                  </div>
                );
              })}
            </>
          ) : (
            <div className="col-span-4 text-center py-4">
              <p className="text-gray-500 font-medium dark:text-gray-400">Loading sync status...</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
