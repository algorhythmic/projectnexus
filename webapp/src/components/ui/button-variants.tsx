import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react"; // Added this line

export const buttonVariants = cva(
  "inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-bold ring-offset-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-black focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 border-2 border-black shadow-[4px_4px_0px_0px_#000] active:shadow-[2px_2px_0px_0px_#000] active:translate-x-[2px] active:translate-y-[2px] dark:border-black dark:shadow-[4px_4px_0px_0px_#000] dark:active:shadow-[2px_2px_0px_0px_#000] dark:focus-visible:ring-gray-500 dark:ring-offset-gray-900",
  // Note: #1f2937 is slate-800. dark:border-black, dark:focus-visible:ring-gray-500, dark:ring-offset-gray-900 (assuming dark page bg)
  {
    variants: {
      variant: {
        default: "bg-yellow-300 text-black hover:bg-yellow-400",
        destructive: "bg-red-500 text-white hover:bg-red-600",
        outline: "bg-white text-black hover:bg-gray-100 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700",
        secondary: "bg-blue-300 text-black hover:bg-blue-400",
        ghost: "border-0 shadow-none bg-transparent hover:bg-yellow-300 active:shadow-none active:translate-x-0 active:translate-y-0 dark:hover:bg-gray-700 dark:hover:text-gray-200",
        link: "border-0 shadow-none text-black underline-offset-4 hover:underline active:shadow-none active:translate-x-0 active:translate-y-0 dark:text-blue-400",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-9 rounded-md px-3",
        lg: "h-11 rounded-md px-8",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export type ButtonVariantProps = VariantProps<typeof buttonVariants>;

// Moved from button.tsx
export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    ButtonVariantProps {
  asChild?: boolean;
}
