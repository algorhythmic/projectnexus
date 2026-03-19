"use client"

import { ColumnDef } from "@tanstack/react-table"
import { Doc } from "../../../convex/_generated/dataModel"
import { ArrowUpDown, MoreHorizontal } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Checkbox } from "@/components/ui/checkbox"

export type ActiveAnomaly = Doc<"activeAnomalies">;

const sortableHeaderClass =
  "font-bold text-black dark:text-white hover:text-black dark:hover:text-black hover:bg-yellow-300 border-2 border-black shadow-[2px_2px_0px_0px_#000] hover:shadow-[4px_4px_0px_0px_#000]"

export function getSeverityStyle(severity: number) {
  if (severity >= 0.7) return "bg-red-300 text-red-800 dark:bg-red-700 dark:text-red-200";
  if (severity >= 0.4) return "bg-yellow-300 text-yellow-800 dark:bg-yellow-600 dark:text-yellow-100";
  return "bg-blue-300 text-blue-800 dark:bg-blue-700 dark:text-blue-200";
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
      return (
        <span className="px-2 py-1 rounded border-2 border-black text-xs font-bold uppercase shadow-[2px_2px_0px_0px_#000] bg-purple-300 text-purple-800 dark:bg-purple-700 dark:text-purple-200">
          {type.replace(/_/g, " ")}
        </span>
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
        <span className={`px-2 py-1 rounded border-2 border-black text-xs font-bold shadow-[2px_2px_0px_0px_#000] ${getSeverityStyle(severity)}`}>
          {severity.toFixed(2)}
        </span>
      );
    },
  },
  {
    accessorKey: "marketCount",
    header: ({ column }) => (
      <Button
        variant="ghost"
        onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
        className={sortableHeaderClass}
      >
        Markets
        <ArrowUpDown className="ml-2 h-4 w-4" />
      </Button>
    ),
    cell: ({ row }) => (
      <div className="font-medium text-gray-900 dark:text-white">{row.getValue("marketCount")}</div>
    ),
  },
  {
    accessorKey: "clusterName",
    header: ({ column }) => (
      <Button
        variant="ghost"
        onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
        className={sortableHeaderClass}
      >
        Cluster
        <ArrowUpDown className="ml-2 h-4 w-4" />
      </Button>
    ),
    cell: ({ row }) => (
      <div className="font-medium text-gray-900 dark:text-white max-w-xs truncate">
        {row.getValue("clusterName")}
      </div>
    ),
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
      <div className="text-sm text-gray-600 dark:text-gray-400 max-w-xs truncate">
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
        <div className="text-gray-700 dark:text-gray-300 whitespace-nowrap">
          {new Date(detectedAt).toLocaleString()}
        </div>
      );
    },
  },
  {
    id: "actions",
    enableHiding: false,
    cell: ({ row }) => {
      const anomaly = row.original;
      return (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="h-8 w-8 p-0 bg-yellow-300 hover:bg-yellow-400 border-2 border-black shadow-[2px_2px_0px_0px_#000] hover:shadow-[4px_4px_0px_0px_#000]">
              <span className="sr-only">Open menu</span>
              <MoreHorizontal className="h-4 w-4 text-black dark:text-black" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="bg-white border-2 border-black shadow-[4px_4px_0px_0px_#000] dark:bg-gray-800 dark:border-black">
            <DropdownMenuLabel className="font-bold dark:text-white">Actions</DropdownMenuLabel>
            <DropdownMenuItem
              onClick={() => void navigator.clipboard.writeText(String(anomaly.anomalyId))}
              className="hover:bg-yellow-300 dark:hover:bg-yellow-500 dark:text-white"
            >
              Copy Anomaly ID
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      );
    },
  },
];
