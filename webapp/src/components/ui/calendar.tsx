import { ChevronLeft, ChevronRight } from "lucide-react"
import { DayPicker } from "react-day-picker"

import * as React from "react"

import { buttonVariants } from "@/components/ui/button"

import { cn } from "@/lib/utils"

export type CalendarProps = React.ComponentProps<typeof DayPicker>

function Calendar({
  className,
  classNames,
  showOutsideDays = true,
  ...props
}: CalendarProps) {
  return (
    <DayPicker
      showOutsideDays={showOutsideDays}
      className={cn(
        "rounded-base! border-2 border-black p-3 font-heading shadow-shadow bg-white dark:bg-gray-800",
        className,
      )}
      classNames={{
        months: "flex flex-col sm:flex-row gap-2",
        month: "flex flex-col gap-4",
        caption:
          "flex justify-center pt-1 relative items-center w-full text-black dark:text-gray-300 font-bold",
        caption_label: "text-sm font-heading font-bold",
        nav: "gap-1 flex items-center",
        nav_button: cn(
          buttonVariants({ variant: "ghost" }),
          "size-7 bg-transparent p-0 hover:bg-yellow-100 dark:hover:bg-yellow-700/30 hover:text-black dark:hover:text-white",
        ),
        nav_button_previous: "absolute left-1",
        nav_button_next: "absolute right-1",
        table: "w-full border-collapse space-y-1",
        head_row: "flex",
        head_cell:
          "text-gray-600 dark:text-gray-300 rounded-base w-9 font-base text-[0.8rem] font-bold uppercase tracking-wider",
        row: "flex w-full mt-2",
        cell: cn(
          "relative p-0 text-center text-sm focus-within:relative focus-within:z-20 [&:has([aria-selected])]:bg-yellow-300 [&:has([aria-selected])]:text-black [&:has([aria-selected].day-range-end)]:rounded-r-base dark:[&:has([aria-selected])]:bg-yellow-300 dark:[&:has([aria-selected])]:text-black [&:has(.day-today)]:!bg-transparent",
          props.mode === "range"
            ? "[&:has(>.day-range-end)]:rounded-r-base [&:has(>.day-range-start)]:rounded-l-base [&:has([aria-selected])]:bg-yellow-300 dark:[&:has([aria-selected])]:bg-yellow-300 first:[&:has([aria-selected])]:rounded-l-base last:[&:has([aria-selected])]:rounded-r-base"
            : "[&:has([aria-selected])]:rounded-base [&:has([aria-selected])]:bg-yellow-300 dark:[&:has([aria-selected])]:bg-yellow-300",
        ),
        day: cn(
          buttonVariants({ variant: "noShadow" }),
          "size-9 p-0 font-base aria-selected:opacity-100 dark:bg-[#374151] dark:text-white dark:border-2 dark:border-black dark:[&:not([aria-selected])]:bg-[#374151]",
        ),
        day_range_start:
          "day-range-start aria-selected:bg-yellow-400 aria-selected:text-black rounded-base dark:aria-selected:bg-yellow-400 dark:aria-selected:text-black",
        day_range_end:
          "day-range-end aria-selected:bg-yellow-400 aria-selected:text-black rounded-base dark:aria-selected:bg-yellow-400 dark:aria-selected:text-black",
        day_selected: "bg-yellow-400 text-black rounded-base dark:bg-yellow-400 dark:text-black hover:bg-yellow-500 dark:hover:bg-yellow-500 dark:!bg-yellow-400 dark:!text-black dark:border-black",
        day_today: "!bg-black !text-white dark:!bg-black dark:!text-white font-bold border-2 border-black",
        day_outside:
          "day-outside text-gray-400 dark:text-gray-500 opacity-50 aria-selected:bg-none dark:bg-transparent dark:border-0",
        day_disabled: "text-gray-400 dark:text-gray-600 opacity-50 rounded-base",
        day_range_middle: "aria-selected:bg-yellow-200 aria-selected:text-black dark:aria-selected:bg-yellow-200 dark:aria-selected:text-black",
        day_hidden: "invisible",
        ...classNames,
      }}
      components={{
        IconLeft: ({ ...props }) => (
          <ChevronLeft className={cn("size-4 text-black dark:text-gray-300")} {...props} />
        ),
        IconRight: ({ ...props }) => (
          <ChevronRight className={cn("size-4 text-black dark:text-gray-300")} {...props} />
        )
      }}
      {...props}
    />
  )
}
Calendar.displayName = "Calendar"

export { Calendar }
