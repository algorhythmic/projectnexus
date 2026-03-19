"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Calendar } from "@/components/ui/calendar";

export function TestPopover() {
  const [date, setDate] = React.useState<Date | undefined>(undefined);
  
  return (
    <div className="p-10">
      <h1 className="text-2xl font-bold mb-4">Popover Test</h1>
      <Popover>
        <PopoverTrigger asChild>
          <Button variant="ghost">
            Open Popover
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-auto p-0">
          <Calendar
            mode="single"
            selected={date}
            onSelect={setDate}
            initialFocus
          />
        </PopoverContent>
      </Popover>
      <div className="mt-4">
        Selected date: {date ? date.toDateString() : "None"}
      </div>
    </div>
  );
}
