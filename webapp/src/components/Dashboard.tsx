import { useState } from "react"
import { SidebarProvider, SidebarInset } from "./ui/sidebar"
import { NeobrutalistSidebar } from "./NeobrutalistSidebar"
import { DashboardOverview } from "./DashboardOverview"
import { MarketsView } from "./MarketsView"
import { AnomalyFeedView } from "./AnomalyFeedView"
import { TrendingTopicsView } from "./TrendingTopicsView"
import { AlertsView } from "./AlertsView"
import { SettingsView } from "./SettingsView";
import { ThemeToggle } from "./ThemeToggle"
import { SignOutButton } from "../SignOutButton"

const viewTitles: { [key: string]: string } = {
  dashboard: "Dashboard",
  markets: "Markets",
  topics: "Trending Topics",
  anomalies: "Anomalies",
  alerts: "Alerts",
  settings: "Settings",
};

export function Dashboard() {
  const [activeView, setActiveView] = useState("dashboard")

  const renderView = () => {
    switch (activeView) {
      case "dashboard":
        return <DashboardOverview onViewChange={setActiveView} />
      case "markets":
        return <MarketsView />
      case "topics":
        return <TrendingTopicsView />
      case "anomalies":
        return <AnomalyFeedView />
      case "alerts":
        return <AlertsView />
      case "settings":
        return <SettingsView />;
      default:
        return <DashboardOverview />
    }
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <SidebarProvider>
        <NeobrutalistSidebar activeView={activeView} onViewChange={setActiveView} className="border-4 border-black shadow-[8px_8px_0px_0px_#000] dark:border-black dark:shadow-[8px_8px_0px_0px_#1f2937]" />
        <SidebarInset className="flex flex-col flex-1 overflow-auto">
          <header className="flex h-16 shrink-0 items-center justify-between gap-2 border-4 border-l-0 border-black bg-white px-4 dark:bg-gray-800 relative z-10">
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold text-black dark:text-white">{viewTitles[activeView] || 'Market Finder'}</h1>
            </div>
            <div className="flex items-center gap-2">
              <ThemeToggle />
              <SignOutButton />
            </div>
          </header>
          <main className="flex-1 overflow-auto p-4 bg-gray-50 dark:bg-gray-900">
            {renderView()}
          </main>
        </SidebarInset>
      </SidebarProvider>
    </div>
  )
}
