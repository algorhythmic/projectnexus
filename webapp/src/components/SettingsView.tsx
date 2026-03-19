import { useMutation } from "convex/react";
import { api } from "../../../convex/_generated/api";
import { useState } from "react";

export function SettingsView() {
  const updatePreferences = useMutation(api.users.updatePreferences);

  const [preferences, setPreferences] = useState({
    categories: [] as string[],
    platforms: [] as string[],
    alertsEnabled: true,
    emailNotifications: false,
  });

  const handleSave = async () => {
    await updatePreferences({
      preferences: {
        ...preferences,
      },
    });
  };

  const availableCategories = [
    "Politics",
    "Sports",
    "Economics",
    "Technology",
    "Entertainment",
    "Science",
    "Weather",
    "Crypto",
  ];

  const availablePlatforms = [
    { value: "kalshi", label: "Kalshi" },
    { value: "polymarket", label: "Polymarket" },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-white border-4 border-black shadow-[8px_8px_0px_0px_#000] p-6 rounded-lg dark:bg-gray-800 dark:border-black dark:shadow-[8px_8px_0px_0px_#000]">
        <p className="text-gray-600 mt-1 font-medium dark:text-gray-400">Customize your Market Finder experience</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Preferences */}
        <div className="bg-white rounded-lg border-4 border-black p-6 shadow-[8px_8px_0px_0px_#000] dark:bg-gray-800 dark:border-black dark:shadow-[8px_8px_0px_0px_#000]">
          <h3 className="text-lg font-semibold text-gray-900 mb-4 dark:text-white">Preferences</h3>

          <div className="space-y-6">
            {/* Categories */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2 dark:text-gray-300">
                Interested Categories
              </label>
              <div className="grid grid-cols-2 gap-2">
                {availableCategories.map((category) => (
                  <label key={category} className="flex items-center">
                    <input
                      type="checkbox"
                      checked={preferences.categories.includes(category)}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setPreferences((prev) => ({
                            ...prev,
                            categories: [...prev.categories, category],
                          }));
                        } else {
                          setPreferences((prev) => ({
                            ...prev,
                            categories: prev.categories.filter((c) => c !== category),
                          }));
                        }
                      }}
                      className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded mr-2 dark:border-black dark:bg-gray-700 dark:focus:ring-blue-600 dark:ring-offset-gray-800"
                    />
                    <span className="text-sm text-gray-700 dark:text-gray-300">{category}</span>
                  </label>
                ))}
              </div>
            </div>

            {/* Platforms */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2 dark:text-gray-300">
                Preferred Platforms
              </label>
              <div className="space-y-2">
                {availablePlatforms.map((platform) => (
                  <label key={platform.value} className="flex items-center">
                    <input
                      type="checkbox"
                      checked={preferences.platforms.includes(platform.value)}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setPreferences((prev) => ({
                            ...prev,
                            platforms: [...prev.platforms, platform.value],
                          }));
                        } else {
                          setPreferences((prev) => ({
                            ...prev,
                            platforms: prev.platforms.filter((p) => p !== platform.value),
                          }));
                        }
                      }}
                      className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded mr-2 dark:border-black dark:bg-gray-700 dark:focus:ring-blue-600 dark:ring-offset-gray-800"
                    />
                    <span className="text-sm text-gray-700 dark:text-gray-300">{platform.label}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Notifications */}
        <div className="bg-white rounded-lg border-4 border-black p-6 shadow-[8px_8px_0px_0px_#000] dark:bg-gray-800 dark:border-black dark:shadow-[8px_8px_0px_0px_#000]">
          <h3 className="text-lg font-semibold text-gray-900 mb-4 dark:text-white">Notifications</h3>

          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h4 className="text-sm font-medium text-gray-900 dark:text-white">Push Alerts</h4>
                <p className="text-sm text-gray-500 dark:text-gray-400">Get notified of new anomalies and market events</p>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={preferences.alertsEnabled}
                  onChange={(e) =>
                    setPreferences((prev) => ({
                      ...prev,
                      alertsEnabled: e.target.checked,
                    }))
                  }
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer dark:bg-gray-700 dark:peer-focus:ring-blue-800 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-black peer-checked:bg-blue-600"></div>
              </label>
            </div>

            <div className="flex items-center justify-between">
              <div>
                <h4 className="text-sm font-medium text-gray-900 dark:text-white">Email Notifications</h4>
                <p className="text-sm text-gray-500 dark:text-gray-400">Receive daily summaries via email</p>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={preferences.emailNotifications}
                  onChange={(e) =>
                    setPreferences((prev) => ({
                      ...prev,
                      emailNotifications: e.target.checked,
                    }))
                  }
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer dark:bg-gray-700 dark:peer-focus:ring-blue-800 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-black peer-checked:bg-blue-600"></div>
              </label>
            </div>
          </div>

          <button
            onClick={() => void handleSave()}
            className="w-full mt-6 bg-blue-300 text-black py-2 px-4 rounded-md border-2 border-black shadow-[4px_4px_0px_0px_#000] hover:shadow-[2px_2px_0px_0px_#000] hover:translate-x-[2px] hover:translate-y-[2px] transition-all font-bold dark:bg-blue-600 dark:text-white dark:border-black dark:shadow-[4px_4px_0px_0px_#000] dark:hover:shadow-[2px_2px_0px_0px_#000]"
          >
            Save Preferences
          </button>
        </div>
      </div>
    </div>
  );
}
