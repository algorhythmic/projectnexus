import { useQuery, useMutation } from "convex/react";
import { api } from "../../../convex/_generated/api";
import { useState } from "react";

export function AlertsView() {
  const alerts = useQuery(api.users.getUserAlerts, { limit: 50 });
  const markAlertsRead = useMutation(api.users.markAlertsRead);
  const [selectedAlerts, setSelectedAlerts] = useState<string[]>([]);

  const handleMarkAsRead = async () => {
    if (selectedAlerts.length > 0) {
      await markAlertsRead({ alertIds: selectedAlerts as any });
      setSelectedAlerts([]);
    }
  };

  const toggleAlert = (alertId: string) => {
    setSelectedAlerts(prev => 
      prev.includes(alertId) 
        ? prev.filter(id => id !== alertId)
        : [...prev, alertId]
    );
  };

  const unreadAlerts = alerts?.filter(alert => !alert.isRead) || [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-white border-4 border-black shadow-[8px_8px_0px_0px_#000] p-6 rounded-lg dark:bg-gray-800 dark:border-black dark:shadow-[8px_8px_0px_0px_#000]">
        <div className="flex justify-between items-center">
          <div>
            {/* Title moved to main app header */}
            <p className="text-gray-600 mt-1 font-medium dark:text-white">
              {unreadAlerts.length} unread alerts
            </p>
          </div>
          {selectedAlerts.length > 0 && (
            <button
              onClick={() => void handleMarkAsRead()}
              className="bg-blue-300 text-black px-4 py-2 rounded-md border-2 border-black shadow-[4px_4px_0px_0px_#000] hover:shadow-[2px_2px_0px_0px_#000] hover:translate-x-[2px] hover:translate-y-[2px] transition-all font-bold dark:bg-blue-600 dark:text-white dark:border-black dark:shadow-[4px_4px_0px_0px_#000] dark:hover:shadow-[2px_2px_0px_0px_#000]"
            >
              Mark {selectedAlerts.length} as Read
            </button>
          )}
        </div>
      </div>

      {/* Alerts List */}
      <div className="space-y-4">
        {alerts?.map((alert) => (
          <div
            key={alert._id}
            className={`bg-white rounded-lg border-4 border-black p-6 shadow-[8px_8px_0px_0px_#000] cursor-pointer transition-all hover:shadow-[4px_4px_0px_0px_#000] hover:translate-x-[4px] hover:translate-y-[4px] dark:bg-gray-800 dark:border-black dark:shadow-[8px_8px_0px_0px_#000] dark:hover:shadow-[4px_4px_0px_0px_#000] ${
              alert.isRead 
                ? "opacity-75 dark:opacity-60" 
                : "bg-yellow-50 dark:bg-yellow-400/10"
            } ${
              selectedAlerts.includes(alert._id) ? "bg-blue-300 dark:bg-blue-500/30" : ""
            }`}
            onClick={() => toggleAlert(alert._id)}
          >
            <div className="flex items-start space-x-4">
              <div className="flex-shrink-0 mt-1">
                <input
                  type="checkbox"
                  checked={selectedAlerts.includes(alert._id)}
                  onChange={() => toggleAlert(alert._id)}
                  className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded dark:border-black dark:bg-gray-700 dark:focus:ring-blue-600 dark:ring-offset-gray-800"
                />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center space-x-2 mb-1">
                  <span className="text-lg">
                    {alert.type === "anomaly" ? "⚠️" :
                     alert.type === "price_change" ? "📈" :
                     "🔔"}
                  </span>
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-white">{alert.title}</h3>
                  <span className={`px-2 py-1 rounded border-2 border-black text-xs font-bold uppercase tracking-wider ${
                    alert.type === "anomaly" ? "bg-orange-300 text-orange-800 dark:bg-orange-700 dark:text-orange-200 dark:border-black" :
                    alert.type === "price_change" ? "bg-blue-300 text-blue-800 dark:bg-blue-700 dark:text-blue-200 dark:border-black" :
                    "bg-gray-300 text-gray-800 dark:bg-gray-600 dark:text-gray-200 dark:border-black"
                  }`}>
                    {alert.type.replace("_", " ")}
                  </span>
                </div>
                <p className="text-sm text-gray-600 mb-2 dark:text-gray-400">{alert.message}</p>
                <div className="flex justify-between items-center">
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    {new Date(alert.createdAt).toLocaleString()}
                  </span>
                  {!alert.isRead && (
                    <span className="w-3 h-3 bg-red-500 rounded-full border-2 border-black dark:border-black"></span>
                  )}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {!alerts?.length && (
        <div className="text-center py-12 bg-white border-4 border-black rounded-lg shadow-[8px_8px_0px_0px_#000] dark:bg-gray-800 dark:border-black dark:shadow-[8px_8px_0px_0px_#000]">
          <div className="text-gray-400 text-6xl mb-4 dark:text-gray-500">🔔</div>
          <h3 className="text-lg font-bold text-gray-900 mb-2 dark:text-white">No Alerts</h3>
          <p className="text-gray-500 font-medium dark:text-gray-400">You'll receive alerts here when opportunities are detected</p>
        </div>
      )}
    </div>
  );
}
