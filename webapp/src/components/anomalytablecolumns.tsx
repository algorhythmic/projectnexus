"use client"

import { ColumnDef } from "@tanstack/react-table"
import { Doc } from "../../../convex/_generated/dataModel"
import { ArrowUpDown, TrendingDown, TrendingUp, Activity, Zap } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"

export type ActiveAnomaly = Doc<"activeAnomalies">;

const sortableHeaderClass =
  "font-bold text-black dark:text-white hover:text-black dark:hover:text-black hover:bg-yellow-300 border-2 border-black shadow-[2px_2px_0px_0px_#000] hover:shadow-[4px_4px_0px_0px_#000]"

export function getSeverityStyle(severity: number) {
  if (severity >= 0.7) return "bg-red-300 text-red-800 dark:bg-red-700 dark:text-red-200";
  if (severity >= 0.4) return "bg-yellow-300 text-yellow-800 dark:bg-yellow-600 dark:text-yellow-100";
  return "bg-blue-300 text-blue-800 dark:bg-blue-700 dark:text-blue-200";
}

export function getSeverityLabel(severity: number): string {
  if (severity >= 0.7) return "High";
  if (severity >= 0.4) return "Medium";
  return "Low";
}

const ANOMALY_TYPE_INFO: Record<string, { label: string; description: string; icon: typeof Activity }> = {
  single_market: {
    label: "Single Market",
    description: "Unusual price or volume movement in one market",
    icon: TrendingUp,
  },
  cluster: {
    label: "Cluster",
    description: "Correlated anomalies across related markets",
    icon: Activity,
  },
  cross_platform: {
    label: "Cross Platform",
    description: "Divergence detected between platforms",
    icon: Zap,
  },
};

export function getAnomalyTypeInfo(type: string) {
  return ANOMALY_TYPE_INFO[type] ?? {
    label: type.replace(/_/g, " "),
    description: "Anomalous market activity detected",
    icon: TrendingDown,
  };
}

/** Format a relative time label from a Unix ms timestamp. */
function formatDetectedTime(ts: number): string {
  const diffMs = Date.now() - ts;
  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(ts).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export const anomalyColumns: ColumnDef<ActiveAnomaly>[] = [
  {
    id: "select",
    size: 60,
    header: ({ table }) => (
      <Checkbox
        checked={
          table.getIsAllPageRowsSelected() ||
          (table.getIsSomePageRowsSelected() && "indeterminate")
        }
        onCheckedChange={(value: boolean) => table.toggleAllPageRowsSelected(!!value)}
        aria-label="Select all"
        className="border-black shadow-[2px_2px_0px_0px_#000] mr-2"
      />
    ),
    cell: ({ row }) => (
      <Checkbox
        checked={row.getIsSelected()}
        onCheckedChange={(value: boolean) => row.toggleSelected(!!value)}
        aria-label="Select row"
        className="border-black shadow-[2px_2px_0px_0px_#000] mr-2"
        onClick={(e) => e.stopPropagation()}
      />
    ),
    enableSorting: false,
    enableHiding: false,
  },
  {
    accessorKey: "anomalyType",
    header: ({ column }) => (
      <Button
        variant="ghost"
        onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
        className={sortableHeaderClass}
      >
        Type
        <ArrowUpDown className="ml-2 h-4 w-4" />
      </Button>
    ),
    cell: ({ row }) => {
      const type = row.getValue("anomalyType") as string;
      const info = getAnomalyTypeInfo(type);
      const Icon = info.icon;
      return (
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded border-2 border-black text-xs font-bold shadow-[2px_2px_0px_0px_#000] bg-purple-300 text-purple-800 dark:bg-purple-700 dark:text-purple-200">
            <Icon className="h-3 w-3" />
            {info.label}
          </span>
        </div>
      );
    },
  },
  {
    accessorKey: "severity",
    header: ({ column }) => (
      <Button
        variant="ghost"
        onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
        className={sortableHeaderClass}
      >
        Severity
        <ArrowUpDown className="ml-2 h-4 w-4" />
      </Button>
    ),
    cell: ({ row }) => {
      const severity = row.getValue("severity") as number;
      return (
        <div className="flex items-center gap-2">
          <span className={`px-2 py-1 rounded border-2 border-black text-xs font-bold shadow-[2px_2px_0px_0px_#000] ${getSeverityStyle(severity)}`}>
            {getSeverityLabel(severity)}
          </span>
          <span className="text-xs font-mono text-gray-500 dark:text-gray-400">
            {severity.toFixed(2)}
          </span>
        </div>
      );
    },
  },
  {
    accessorKey: "summary",
    header: ({ column }) => (
      <Button
        variant="ghost"
        onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
        className={sortableHeaderClass}
      >
        Summary
        <ArrowUpDown className="ml-2 h-4 w-4" />
      </Button>
    ),
    cell: ({ row }) => (
      <div className="text-sm text-gray-700 dark:text-gray-300 max-w-md line-clamp-2">
        {row.getValue("summary")}
      </div>
    ),
  },
  {
    accessorKey: "detectedAt",
    header: ({ column }) => (
      <Button
        variant="ghost"
        onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
        className={sortableHeaderClass}
      >
        Detected
        <ArrowUpDown className="ml-2 h-4 w-4" />
      </Button>
    ),
    cell: ({ row }) => {
      const detectedAt = row.getValue("detectedAt") as number;
      return (
        <div className="text-sm text-gray-700 dark:text-gray-300 whitespace-nowrap">
          {formatDetectedTime(detectedAt)}
        </div>
      );
    },
  },
];
