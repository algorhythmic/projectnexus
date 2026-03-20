"use client"

import { ColumnDef } from "@tanstack/react-table"
import { Doc } from "../../../convex/_generated/dataModel"
import { ArrowUpDown, ExternalLink, Copy, MoreHorizontal, ChevronRight, ChevronDown } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Checkbox } from "@/components/ui/checkbox"

export type NexusMarket = Doc<"nexusMarkets">;

/** Extended row type with optional grouping metadata. */
export type MarketRow = NexusMarket & {
  _eventKey?: string;
  _groupSize?: number;
  _groupTitle?: string;
  _isExpanded?: boolean;
  _isChild?: boolean;
};

/** Derive the Kalshi event key from a market ticker (first segment before "-"). */
export function getEventKey(externalId: string): string {
  return externalId.split("-")[0];
}

/**
 * Group flat market rows by event key. Single-market groups pass through;
 * multi-market groups become a parent row (with _groupSize) followed by
 * child rows (with _isChild) when expanded.
 */
export function groupMarkets(
  markets: NexusMarket[],
  expandedKeys: Set<string>,
): MarketRow[] {
  const groups = new Map<string, NexusMarket[]>();
  for (const m of markets) {
    const key = getEventKey(m.externalId);
    const group = groups.get(key) || [];
    group.push(m);
    groups.set(key, group);
  }

  const rows: MarketRow[] = [];
  for (const [key, members] of groups) {
    if (members.length === 1) {
      rows.push({ ...members[0], _eventKey: key });
    } else {
      const isExpanded = expandedKeys.has(key);
      // Use event title from any member (all share the same event)
      const groupTitle = members.find((m) => m.eventTitle)?.eventTitle || "";
      // Parent row uses the first market as representative but with
      // a synthetic _id to avoid duplicate keys when expanded
      // (children include members[0] with its original _id)
      rows.push({
        ...members[0],
        _id: `group-${key}` as any,
        _eventKey: key,
        _groupSize: members.length,
        _groupTitle: groupTitle,
        _isExpanded: isExpanded,
      });
      if (isExpanded) {
        for (const m of members) {
          rows.push({ ...m, _eventKey: key, _isChild: true });
        }
      }
    }
  }
  return rows;
}

function getPlatformUrl(platform: string, externalId: string): string {
  if (platform === "kalshi") {
    // Kalshi URLs use the event/series ticker (first segment of the market ticker)
    // e.g. KXHIGHNY-26MAR25-65 → kalshi.com/markets/kxhighny
    const eventTicker = externalId.split("-")[0].toLowerCase();
    return `https://kalshi.com/markets/${eventTicker}`;
  }
  if (platform === "polymarket") {
    return `https://polymarket.com/event/${externalId}`;
  }
  return "#";
}

export const columns: ColumnDef<MarketRow>[] = [
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
    accessorKey: "title",
    header: ({ column }) => {
      return (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          className="font-bold text-black dark:text-white hover:text-black dark:hover:text-black hover:bg-yellow-300 border-2 border-black shadow-[2px_2px_0px_0px_#000] hover:shadow-[4px_4px_0px_0px_#000]"
        >
          Title
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      )
    },
    cell: ({ row }) => {
      const market = row.original;
      const url = getPlatformUrl(market.platform, market.externalId);
      const isGroup = (market._groupSize ?? 0) > 1;
      const isChild = market._isChild;

      return (
        <div className={`flex items-center gap-1.5 max-w-[400px] ${isChild ? "pl-7 border-l-2 border-blue-300 dark:border-blue-600 ml-2" : ""}`}>
          {isGroup && (
            <span className="shrink-0 text-gray-500 dark:text-gray-400">
              {market._isExpanded ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
            </span>
          )}
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className={`font-medium hover:text-blue-600 dark:hover:text-blue-400 hover:underline inline-flex items-center gap-1 min-w-0 ${
              isChild
                ? "text-gray-700 dark:text-gray-300 text-sm"
                : "text-gray-900 dark:text-white"
            }`}
            onClick={(e) => e.stopPropagation()}
          >
            <span className="line-clamp-2">{isGroup && market._groupTitle ? market._groupTitle : market.title}</span>
            <ExternalLink className="h-3 w-3 opacity-0 group-hover:opacity-100 shrink-0" />
          </a>
          {isGroup && (
            <span className="shrink-0 ml-1 px-1.5 py-0.5 text-xs font-bold bg-blue-200 text-blue-800 dark:bg-blue-700 dark:text-blue-200 border border-black rounded whitespace-nowrap">
              {market._groupSize} outcomes
            </span>
          )}
        </div>
      );
    },
  },
  {
    accessorKey: "platform",
    header: ({ column }) => {
      return (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          className="font-bold text-black dark:text-white hover:text-black dark:hover:text-black hover:bg-yellow-300 border-2 border-black shadow-[2px_2px_0px_0px_#000] hover:shadow-[4px_4px_0px_0px_#000]"
        >
          Platform
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      )
    },
    cell: ({ row }) => {
      const platform = row.getValue("platform") as string;
      return <div className="text-gray-700 dark:text-gray-300">{platform.charAt(0).toUpperCase() + platform.slice(1)}</div>;
    },
  },
  {
    accessorKey: "lastPrice",
    header: ({ column }) => (
      <Button
        variant="ghost"
        onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
        className="font-bold text-black dark:text-white hover:text-black dark:hover:text-black hover:bg-yellow-300 border-2 border-black shadow-[2px_2px_0px_0px_#000] hover:shadow-[4px_4px_0px_0px_#000] text-right"
      >
        Price
        <ArrowUpDown className="ml-2 h-4 w-4" />
      </Button>
    ),
    cell: ({ row }) => {
      const price = row.getValue("lastPrice") as number | null | undefined;
      if (price == null) return <div className="text-right font-medium text-gray-400 dark:text-gray-500">N/A</div>;
      const noPrice = 1 - price;
      return (
        <div className="flex items-center justify-end gap-2">
          <span className="inline-flex items-center gap-1">
            <span className="text-[10px] font-bold text-emerald-700 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-900/40 px-1 rounded">YES</span>
            <span className="font-semibold text-gray-900 dark:text-white">${price.toFixed(2)}</span>
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="text-[10px] font-bold text-red-700 dark:text-red-400 bg-red-100 dark:bg-red-900/40 px-1 rounded">NO</span>
            <span className="font-semibold text-gray-500 dark:text-gray-400">${noPrice.toFixed(2)}</span>
          </span>
        </div>
      );
    },
  },
  {
    accessorKey: "category",
    header: ({ column }) => (
      <Button
        variant="ghost"
        onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
        className="font-bold text-black dark:text-white hover:text-black dark:hover:text-black hover:bg-yellow-300 border-2 border-black shadow-[2px_2px_0px_0px_#000] hover:shadow-[4px_4px_0px_0px_#000]"
      >
        Category
        <ArrowUpDown className="ml-2 h-4 w-4" />
      </Button>
    ),
    cell: ({ row }) => <div className="text-gray-700 dark:text-gray-300">{row.getValue("category")}</div>,
  },
  {
    accessorKey: "endDate",
    header: ({ column }) => (
      <Button
        variant="ghost"
        onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
        className="font-bold text-black dark:text-white hover:text-black dark:hover:text-black hover:bg-yellow-300 border-2 border-black shadow-[2px_2px_0px_0px_#000] hover:shadow-[4px_4px_0px_0px_#000]"
      >
        Resolves
        <ArrowUpDown className="ml-2 h-4 w-4" />
      </Button>
    ),
    cell: ({ row }) => {
      const endDate = row.getValue("endDate") as string | null | undefined;
      if (!endDate) return <div className="text-gray-400 dark:text-gray-500">—</div>;
      const date = new Date(endDate);
      const now = new Date();
      const diffMs = date.getTime() - now.getTime();
      const diffDays = Math.ceil(diffMs / (1000 * 60 * 60 * 24));
      let label: string;
      if (diffDays < 0) label = "Expired";
      else if (diffDays === 0) label = "Today";
      else if (diffDays === 1) label = "Tomorrow";
      else if (diffDays < 7) label = `${diffDays}d`;
      else if (diffDays < 365) label = date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
      else label = date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
      return (
        <div className={`text-sm whitespace-nowrap ${diffDays <= 1 ? "font-bold text-orange-600 dark:text-orange-400" : "text-gray-700 dark:text-gray-300"}`}>
          {label}
        </div>
      );
    },
  },
  {
    accessorKey: "syncedAt",
    header: ({ column }) => {
      return (
        <Button
          variant="ghost"
          onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
          className="font-bold text-black dark:text-white hover:text-black dark:hover:text-black hover:bg-yellow-300 border-2 border-black shadow-[2px_2px_0px_0px_#000] hover:shadow-[4px_4px_0px_0px_#000]"
        >
          Last Updated
          <ArrowUpDown className="ml-2 h-4 w-4" />
        </Button>
      )
    },
    cell: ({ row }) => {
      const syncedAt = row.getValue("syncedAt") as number;
      return <div className="text-gray-700 dark:text-gray-300">{new Date(syncedAt).toLocaleString()}</div>;
    },
  },
  {
    id: "actions",
    enableHiding: false,
    cell: ({ row }) => {
      const market = row.original;

      return (
        <DropdownMenu modal={false}>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              className="h-8 w-8 p-0 bg-yellow-300 hover:bg-yellow-400 border-2 border-black shadow-[2px_2px_0px_0px_#000] hover:shadow-[4px_4px_0px_0px_#000]"
              onClick={(e) => e.stopPropagation()}
            >
              <span className="sr-only">Open menu</span>
              <MoreHorizontal className="h-4 w-4 text-black dark:text-black" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="bg-white border-2 border-black shadow-[4px_4px_0px_0px_#000] dark:bg-gray-800 dark:border-black">
            <DropdownMenuLabel className="font-bold dark:text-white">Actions</DropdownMenuLabel>
            <DropdownMenuItem
              onClick={() => window.open(getPlatformUrl(market.platform, market.externalId), "_blank", "noopener,noreferrer")}
              className="cursor-pointer hover:bg-yellow-300 dark:hover:bg-yellow-500 dark:text-white"
            >
              <ExternalLink className="mr-2 h-4 w-4" />
              View on {market.platform === "kalshi" ? "Kalshi" : "Polymarket"}
            </DropdownMenuItem>
            <DropdownMenuSeparator className="bg-gray-300 dark:bg-gray-600" />
            <DropdownMenuItem
              onClick={() => void navigator.clipboard.writeText(market.title)}
              className="cursor-pointer hover:bg-yellow-300 dark:hover:bg-yellow-500 dark:text-white"
            >
              <Copy className="mr-2 h-4 w-4" />
              Copy Title
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() => void navigator.clipboard.writeText(market.externalId)}
              className="cursor-pointer hover:bg-yellow-300 dark:hover:bg-yellow-500 dark:text-white"
            >
              <Copy className="mr-2 h-4 w-4" />
              Copy External ID
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )
    },
  },
]
