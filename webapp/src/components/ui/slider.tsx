import * as React from "react"
import * as SliderPrimitive from "@radix-ui/react-slider"

import { cn } from "@/lib/utils"

const Slider = React.forwardRef<
  React.ElementRef<typeof SliderPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SliderPrimitive.Root>
>(({ className, value, ...props }, ref) => {
  // Ensure value is an array for range slider
  const values = Array.isArray(value) ? value : [value || 0];
  
  return (
    <SliderPrimitive.Root
      ref={ref}
      value={values}
      className={cn(
        "relative flex w-full touch-none select-none items-center",
        className
      )}
      {...props}
    >
      <SliderPrimitive.Track className="relative h-2 w-full grow overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
        <SliderPrimitive.Range className="absolute h-full bg-black dark:bg-yellow-300" />
      </SliderPrimitive.Track>
      {values.map((_, i) => (
        <SliderPrimitive.Thumb
          key={i}
          className={cn(
            "block h-5 w-5 rounded-full border-2 bg-white ring-offset-white",
            "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2",
            "disabled:pointer-events-none disabled:opacity-50",
            // Light mode styles
            "border-black focus-visible:ring-slate-950",
            // Dark mode styles
            "dark:border-yellow-300 dark:bg-slate-900 dark:ring-offset-slate-950 dark:focus-visible:ring-yellow-400"
          )}
        />
      ))}
    </SliderPrimitive.Root>
  );
});

Slider.displayName = SliderPrimitive.Root.displayName;

export { Slider };
