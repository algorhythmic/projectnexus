"use client"

import * as React from "react"
import {
  ColumnDef,
  ColumnFiltersState,
  SortingState,
  VisibilityState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table"

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { useResponsiveLayout } from "@/hooks/use-responsive-layout"

interface DataTableProps<TData, TValue> {
  columns: ColumnDef<TData, TValue>[]
  data: TData[]
  externalGlobalFilter?: string
  onSelectionChange?: (selectedRows: TData[]) => void
  onRowClick?: (row: TData) => void
  resetSelectionTrigger?: number
  renderSelectionToolbar?: (selectedRows: TData[], clearSelection: () => void) => React.ReactNode
  renderCard?: (item: TData, isSelected: boolean, toggleSelected: (value: boolean) => void) => React.ReactNode
  tabletHiddenColumns?: string[]
  onLoadMore?: () => void
  loadMoreStatus?: string
}

export function MarketDataTable<TData extends { _id: string }, TValue>({
  columns,
  data,
  externalGlobalFilter,
  onSelectionChange,
  onRowClick,
  resetSelectionTrigger,
  renderSelectionToolbar,
  renderCard,
  tabletHiddenColumns,
  onLoadMore,
  loadMoreStatus,
}: DataTableProps<TData, TValue>) {
  const layoutMode = useResponsiveLayout()
  const [sorting, setSorting] = React.useState<SortingState>([])
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([])
  const [globalFilter, setGlobalFilter] = React.useState("")
  const [columnVisibility, setColumnVisibility] = React.useState<VisibilityState>({})
  const [rowSelection, setRowSelection] = React.useState({})

  React.useEffect(() => {
    if (externalGlobalFilter !== undefined) {
      setGlobalFilter(externalGlobalFilter);
    }
  }, [externalGlobalFilter]);

  React.useEffect(() => {
    if (resetSelectionTrigger !== undefined) {
      setRowSelection({});
    }
  }, [resetSelectionTrigger]);

  // Hide columns on tablet, restore on desktop
  React.useEffect(() => {
    if (!tabletHiddenColumns?.length) return;

    if (layoutMode === 'tablet') {
      setColumnVisibility(prev => {
        const next = { ...prev };
        for (const col of tabletHiddenColumns) {
          next[col] = false;
        }
        return next;
      });
    } else if (layoutMode === 'desktop') {
      setColumnVisibility(prev => {
        const next = { ...prev };
        for (const col of tabletHiddenColumns) {
          delete next[col];
        }
        return next;
      });
    }
  }, [layoutMode, tabletHiddenColumns]);

  const clearSelection = React.useCallback(() => {
    setRowSelection({});
  }, []);

  // Count child rows so they don't consume page slots — expanded
  // groups should always show all their children regardless of page size
  const childRowCount = React.useMemo(
    () => data.filter((r) => (r as Record<string, unknown>)._isChild).length,
    [data],
  );
  const BASE_PAGE_SIZE = 10;
  const [pageIndex, setPageIndex] = React.useState(0);

  const table = useReactTable({
    data,
    columns,
    getRowId: (row) => row._id,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    onSortingChange: setSorting,
    getSortedRowModel: getSortedRowModel(),
    onColumnFiltersChange: setColumnFilters,
    getFilteredRowModel: getFilteredRowModel(),
    onGlobalFilterChange: setGlobalFilter,
    onColumnVisibilityChange: setColumnVisibility,
    onRowSelectionChange: setRowSelection,
    onPaginationChange: (updater) => {
      const next = typeof updater === "function"
        ? updater({ pageIndex, pageSize: BASE_PAGE_SIZE + childRowCount })
        : updater;
      setPageIndex(next.pageIndex);
    },
    enableRowSelection: true,
    state: {
      sorting,
      columnFilters,
      globalFilter,
      columnVisibility,
      rowSelection,
      pagination: { pageIndex, pageSize: BASE_PAGE_SIZE + childRowCount },
    },
  })

  React.useEffect(() => {
    if (table && onSelectionChange) {
      const selectedRowsData = table.getSelectedRowModel().rows.map(row => row.original);
      onSelectionChange(selectedRowsData);
    }
  }, [rowSelection, table, onSelectionChange]);

  const tableContainerStyles = "bg-white border-4 border-black shadow-[8px_8px_0px_0px_#000] rounded-lg p-1 dark:bg-gray-800 dark:border-black dark:shadow-[8px_8px_0px_0px_#000]"
  const buttonStyles = "font-bold text-black bg-yellow-300 hover:bg-yellow-400 border-2 border-black shadow-[2px_2px_0px_0px_#000] hover:shadow-[4px_4px_0px_0px_#000] active:shadow-[1px_1px_0px_0px_#000] active:translate-x-[2px] active:translate-y-[2px] dark:text-black dark:hover:bg-yellow-500"

  const selectedRows = table.getSelectedRowModel().rows.map(row => row.original);
  const isMobileCards = layoutMode === 'mobile' && renderCard;

  return (
    <div className={tableContainerStyles}>
      {renderSelectionToolbar && selectedRows.length > 0 && (
        <div className="mb-2">
          {renderSelectionToolbar(selectedRows, clearSelection)}
        </div>
      )}

      {isMobileCards ? (
        /* ─── Mobile Card Layout ─── */
        <div className="space-y-3 p-2">
          <div className="flex items-center gap-2 px-2 py-1">
            <Checkbox
              checked={
                table.getIsAllPageRowsSelected() ||
                (table.getIsSomePageRowsSelected() && "indeterminate")
              }
              onCheckedChange={(value: boolean) => table.toggleAllPageRowsSelected(!!value)}
              aria-label="Select all"
              className="border-black shadow-[2px_2px_0px_0px_#000]"
            />
            <span className="text-sm font-bold text-gray-600 dark:text-gray-400">
              Select all ({table.getFilteredRowModel().rows.length})
            </span>
          </div>

          {table.getRowModel().rows.length ? (
            table.getRowModel().rows.map((row) => (
              <div key={row.id}>
                {renderCard(
                  row.original,
                  row.getIsSelected(),
                  (value: boolean) => row.toggleSelected(value)
                )}
              </div>
            ))
          ) : (
            <div className="py-8 text-center font-medium text-gray-500 dark:text-gray-400">
              No results.
            </div>
          )}
        </div>
      ) : (
        /* ─── Table Layout (Tablet + Desktop) ─── */
        <div className="rounded-md border-2 border-black dark:border-black">
          <Table>
            <TableHeader className="bg-gray-200 dark:bg-gray-700">
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id} className="border-b-2 border-black dark:border-black">
                  {headerGroup.headers.map((header) => {
                    const isSticky = header.column.id === "actions";
                    return (
                      <TableHead
                        key={header.id}
                        className={`px-4 py-3 text-left text-xs font-bold text-gray-600 uppercase tracking-wider dark:text-gray-300 border-r-2 border-black last:border-r-0 dark:border-black ${
                          isSticky ? "sticky right-0 z-20 bg-gray-200 dark:bg-gray-700" : ""
                        }`}
                      >
                        {header.isPlaceholder
                          ? null
                          : flexRender(
                              header.column.columnDef.header,
                              header.getContext()
                            )}
                      </TableHead>
                    )
                  })}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows?.length ? (
                table.getRowModel().rows.map((row) => (
                  <TableRow
                    key={row.id}
                    data-state={row.getIsSelected() && "selected"}
                    className={`group border-b border-gray-300 dark:border-gray-700 ${
                      (row.original as Record<string, unknown>)._isChild
                        ? "bg-blue-50/50 dark:bg-blue-950/20 hover:bg-blue-100 dark:hover:bg-blue-900/30"
                        : "hover:bg-yellow-200 dark:hover:bg-yellow-500/30"
                    } ${
                      ((row.original as Record<string, unknown>)._groupSize as number ?? 0) > 1
                        ? "cursor-pointer bg-gray-50 dark:bg-gray-700/50"
                        : ""
                    }`}
                    onClick={() => onRowClick?.(row.original)}
                  >
                    {row.getVisibleCells().map((cell) => {
                      const isSticky = cell.column.id === "actions";
                      return (
                        <TableCell
                          key={cell.id}
                          className={`px-4 py-3 border-r border-gray-200 last:border-r-0 dark:border-gray-600 ${
                            isSticky ? "sticky right-0 z-10 bg-white dark:bg-gray-800 group-hover:bg-yellow-200 dark:group-hover:bg-yellow-500/30 border-l-2 border-l-gray-300 dark:border-l-gray-600" : ""
                          }`}
                        >
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext()
                          )}
                        </TableCell>
                      );
                    })}
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell
                    colSpan={columns.length}
                    className="h-24 text-center font-medium text-gray-500 dark:text-gray-400"
                  >
                    No results.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      )}

      {/* ─── Pagination Footer ─── */}
      <div className="flex items-center justify-between py-4 px-2">
        <div className="text-sm text-muted-foreground font-medium text-gray-600 dark:text-gray-400">
          {table.getFilteredSelectedRowModel().rows.length} of{" "}
          {table.getFilteredRowModel().rows.length} selected.
        </div>
        <div className="flex items-center space-x-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => table.previousPage()}
            disabled={!table.getCanPreviousPage()}
            className={buttonStyles}
          >
            Previous
          </Button>
          {onLoadMore && loadMoreStatus === "CanLoadMore" && !table.getCanNextPage() && (
            <Button
              variant="ghost"
              size="sm"
              onClick={onLoadMore}
              className={buttonStyles}
            >
              Load More
            </Button>
          )}
          {loadMoreStatus === "LoadingMore" && (
            <span className="text-sm font-medium text-gray-500 dark:text-gray-400 px-3">
              Loading...
            </span>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => table.nextPage()}
            disabled={!table.getCanNextPage()}
            className={buttonStyles}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  )
}
