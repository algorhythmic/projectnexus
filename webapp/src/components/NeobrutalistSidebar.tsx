import {
  TrendingUp,
  Settings,
  Home,
  Search,
  Bell,
  AlertTriangle,
  ChevronUp,
  User2,
  ChartColumnIncreasing,
} from "lucide-react"

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  SidebarTrigger,
} from "./ui/sidebar"
import { useQuery } from "convex/react"
import { api } from "../../../convex/_generated/api"
import { useSidebar } from "./ui/sidebar";
import { cn } from "../lib/utils"; // Import cn utility

// Menu items.
const items = [
  {
    title: "Dashboard",
    url: "#",
    icon: Home,
    view: "dashboard",
  },
  {
    title: "Markets",
    url: "#",
    icon: Search,
    view: "markets",
  },
  {
    title: "Trending",
    url: "#",
    icon: TrendingUp,
    view: "topics",
  },
  {
    title: "Anomalies",
    url: "#",
    icon: AlertTriangle,
    view: "anomalies",
  },
  {
    title: "Alerts",
    url: "#",
    icon: Bell,
    view: "alerts",
  },
  {
    title: "Settings",
    url: "#",
    icon: Settings,
    view: "settings",
  },
]

interface NeobrutalistSidebarProps {
  activeView: string;
  onViewChange: (view: string) => void;
  onMobileNavItemClick?: () => void; // Added to handle mobile overlay collapse
  className?: string; // Allow className to be passed through
}

export function NeobrutalistSidebar({ activeView, onViewChange, onMobileNavItemClick, className }: NeobrutalistSidebarProps) {
  const activeAlertCount = useQuery(api.users.getUnreadAlertCount) ?? 0;
  const user = useQuery(api.auth.loggedInUser)
  const { state, isMobile } = useSidebar(); // isMobile from context
  const isCollapsed = state === "collapsed"

  return (
    <Sidebar 
      collapsible="icon" 
      className={className} // Use passed className, width controlled by ui/sidebar.tsx
    >
      <SidebarHeader className="h-16 border-b-4 border-black bg-yellow-300 dark:bg-gray-800 flex items-center justify-start px-4 -mt-[4px] -ml-[4px] w-[calc(100%+4px)]">
        <div className={cn("flex items-center w-full", isCollapsed ? "justify-center" : "gap-2 justify-start")}>
          <SidebarTrigger 
            className="h-8 w-8 p-1 bg-green-500 text-white border-2 border-black rounded-md shadow-[3px_3px_0px_0px_#000] hover:shadow-[1px_1px_0px_0px_#000] hover:translate-x-[1px] hover:translate-y-[1px] active:shadow-none active:translate-x-[2px] active:translate-y-[2px] transition-all focus:outline-none dark:bg-green-600 dark:text-white dark:border-black dark:shadow-[3px_3px_0px_0px_#000] dark:hover:shadow-[1px_1px_0px_0px_#000]"
          >
            <ChartColumnIncreasing className="h-6 w-6 text-black" />
          </SidebarTrigger>
          {!isCollapsed && (
            <div className="grid flex-1 text-left text-sm leading-tight min-w-0">
              <span className="truncate font-bold text-black dark:text-white">Market Finder</span>
              <span className="truncate text-xs text-black/70 dark:text-gray-400">Prediction Markets</span>
            </div>
          )}
        </div>
      </SidebarHeader>
      <SidebarContent className="bg-white dark:bg-gray-900">
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {items.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton 
                    asChild
                    isActive={activeView === item.view}
                    className="hover:bg-yellow-300 data-[active=true]:bg-yellow-300 data-[active=true]:border-2 data-[active=true]:border-black data-[active=true]:shadow-[2px_2px_0px_0px_#000] dark:text-gray-300 dark:hover:bg-gray-700 dark:data-[active=true]:bg-gray-600 dark:data-[active=true]:text-white dark:data-[active=true]:border-black dark:data-[active=true]:shadow-[2px_2px_0px_0px_#000]"
                  >
                    <button 
                      onClick={() => {
                      onViewChange(item.view);
                      if (isMobile && state === "expanded" && onMobileNavItemClick) {
                        onMobileNavItemClick();
                      }
                    }}
                      className={isCollapsed ? "flex items-center justify-center w-full h-full" : "flex items-center gap-3 w-full"}
                    >
                      <div className="relative">
                        <item.icon className="h-5 w-5 flex-shrink-0" />
                        {item.title === "Alerts" && activeAlertCount > 0 && (
                          <div className="absolute -top-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-xs text-white">
                            {activeAlertCount}
                          </div>
                        )}
                      </div>
                      {!isCollapsed && <span className="font-medium truncate">{item.title}</span>}
                    </button>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="border-t-4 border-black bg-blue-300 dark:bg-gray-800">
        <SidebarMenu>
          <SidebarMenuItem className="flex justify-center">
            <SidebarMenuButton 
              size="lg"
              className={`hover:bg-blue-400 border-2 border-black shadow-[2px_2px_0px_0px_#000] dark:text-gray-300 dark:hover:bg-gray-700 dark:border-black dark:shadow-[2px_2px_0px_0px_#000] ${
                isCollapsed ? 'w-8 h-8 mx-auto' : ''
              } flex items-center justify-center`}
            >
              <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-black text-white dark:bg-gray-700 dark:text-gray-200 dark:border-black flex-shrink-0">
                <User2 className="size-4" />
              </div>
              {!isCollapsed && (
                <>
                  <div className="grid flex-1 text-left text-sm leading-tight min-w-0">
                    <span className="truncate font-bold text-black dark:text-white">
                      {user?.name || "Anonymous"}
                    </span>
                    <span className="truncate text-xs text-black/70 dark:text-gray-400">
                      {user?.email || "Not signed in"}
                    </span>
                  </div>
                  <ChevronUp className="ml-auto size-4 dark:text-gray-300 flex-shrink-0" />
                </>
              )}
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
