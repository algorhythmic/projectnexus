import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { VariantProps, cva } from "class-variance-authority"
import { PanelLeft } from "lucide-react"

import { cn } from "../../lib/utils"
import { Button } from "./button"
import { Dialog, DialogContent, DialogOverlay } from "./dialog"

const SIDEBAR_COOKIE_NAME = "sidebar:state"
const SIDEBAR_COOKIE_MAX_AGE = 60 * 60 * 24 * 7
const SIDEBAR_WIDTH = "16rem"
const SIDEBAR_WIDTH_MOBILE = "18rem"
const SIDEBAR_WIDTH_ICON = "3rem"
const SIDEBAR_KEYBOARD_SHORTCUT = "b"

type SidebarContext = {
  state: "expanded" | "collapsed" // Reflects true visual state (expanded/collapsed) for current mode (desktop/mobile)
  open: boolean // For desktop: actual open state. For mobile: if overlay is open.
  setOpen: (open: boolean | ((prevState: boolean) => boolean)) => void // For desktop: sets actual open. For mobile: sets overlay open.
  openMobile: boolean // Raw state of mobile overlay (kept for clarity, though `open` serves this on mobile)
  setOpenMobile: (open: boolean | ((prevState: boolean) => boolean)) => void // Raw setter for mobile overlay
  isMobile: boolean
  toggleSidebar: () => void
}

// Define SidebarContentProps based on SidebarContent's expected props
type SidebarContentProps = React.ComponentProps<"div"> & {
  isIconOnly?: boolean;
};

const SidebarContext = React.createContext<SidebarContext | null>(null)

function useSidebar() {
  const context = React.useContext(SidebarContext)
  if (!context) {
    throw new Error("useSidebar must be used within a SidebarProvider.")
  }

  return context
}

const SidebarProvider = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div"> & {
    defaultOpen?: boolean
    open?: boolean
    onOpenChange?: (open: boolean) => void
  }
>(
  (
    {
      defaultOpen = true,
      open: openProp,
      onOpenChange: setOpenProp,
      className,
      style,
      children,
      ...props
    },
    ref
  ) => {
    const [openMobile, _setOpenMobile] = React.useState(false)
    const [isMobile, setIsMobile] = React.useState(false)

    React.useEffect(() => {
      const checkMobile = () => setIsMobile(window.innerWidth < 768); // md breakpoint (768px)
      checkMobile();
      window.addEventListener("resize", checkMobile);
      return () => window.removeEventListener("resize", checkMobile);
    }, []);

    // This is the internal state of the sidebar.
    // We use openProp and setOpenProp for control from outside the component.
    const [_openDesktop, _setOpenDesktop] = React.useState(defaultOpen)
    const openDesktop = openProp ?? _openDesktop; // Explicitly for desktop state
    const setOpenDesktopCookie = React.useCallback((desktopState: boolean) => {
      document.cookie = `${SIDEBAR_COOKIE_NAME}=${desktopState}; path=/; max-age=${SIDEBAR_COOKIE_MAX_AGE}`;
    }, []);

    const setOpenDesktop = React.useCallback(
      (value: boolean | ((prevState: boolean) => boolean)) => {
        const newState = typeof value === "function" ? value(openDesktop) : value;
        if (setOpenProp) { // If controlled from outside for desktop
          setOpenProp(newState);
        } else {
          _setOpenDesktop(newState);
        }
        setOpenDesktopCookie(newState);
      },
      [setOpenProp, openDesktop, _setOpenDesktop, setOpenDesktopCookie]
    );

    const setOpenMobile = React.useCallback(
      (value: boolean | ((prevState: boolean) => boolean)) => {
        _setOpenMobile(typeof value === 'function' ? value(openMobile) : value);
        // Mobile state is not typically persisted in a cookie the same way
      },
      [openMobile, _setOpenMobile]
    );

    // Helper to toggle the sidebar.
    const toggleSidebar = React.useCallback(() => {
      if (isMobile) {
        setOpenMobile(prev => !prev);
      } else {
        setOpenDesktop(prev => !prev);
      }
    }, [isMobile, setOpenMobile, setOpenDesktop]);

    // Adds a keyboard shortcut to toggle the sidebar.
    React.useEffect(() => {
      const handleKeyDown = (event: KeyboardEvent) => {
        if (
          event.key === SIDEBAR_KEYBOARD_SHORTCUT &&
          (event.metaKey || event.ctrlKey)
        ) {
          event.preventDefault()
          toggleSidebar()
        }
      }

      window.addEventListener("keydown", handleKeyDown)
      return () => window.removeEventListener("keydown", handleKeyDown)
    }, [toggleSidebar])

    // Determine effective state, open status, and setter for the context
    const effectiveState = isMobile ? (openMobile ? "expanded" : "collapsed") : (openDesktop ? "expanded" : "collapsed");
    const effectiveOpen = isMobile ? openMobile : openDesktop;
    const effectiveSetOpen = isMobile ? setOpenMobile : setOpenDesktop;

    const contextValue = React.useMemo<SidebarContext>(
      () => ({
        state: effectiveState,
        open: effectiveOpen,
        setOpen: effectiveSetOpen,
        isMobile,
        openMobile, // Keep raw mobile state for specific needs if any
        setOpenMobile, // Keep raw mobile setter
        toggleSidebar,
      }),
      [effectiveState, effectiveOpen, effectiveSetOpen, isMobile, openMobile, setOpenMobile, toggleSidebar]
    );

    return (
      <SidebarContext.Provider value={contextValue}>
        <div
          style={
            {
              "--sidebar-width": SIDEBAR_WIDTH,
              "--sidebar-width-icon": SIDEBAR_WIDTH_ICON,
              "--sidebar-width-mobile": SIDEBAR_WIDTH_MOBILE, // Used by offcanvas mobile
              "--sidebar-mobile-expanded-inline-width": "14rem", // For new inline mobile expanded state
              ...style,
            } as React.CSSProperties
          }
          className={cn(
            "group/sidebar-wrapper flex min-h-svh w-full has-[[data-variant=inset]]:bg-sidebar",
            className
          )}
          ref={ref}
          {...props}
        >
          {children}
        </div>
      </SidebarContext.Provider>
    )
  }
)
SidebarProvider.displayName = "SidebarProvider"

const Sidebar = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div"> & {
    variant?: "sidebar" | "floating" | "inset";
    collapsible?: "offcanvas" | "icon" | "none"; // This is a prop for Sidebar itself
  }
>(
  (
    {
      variant = "sidebar",
      collapsible = "offcanvas", // Default collapsible type for this component instance
      className,
      children,
      ...props
    },
    ref
  ) => {
    const { isMobile, state, setOpen } = useSidebar();

    // 1. Handle "none" collapsible type (always expanded on desktop, hidden on mobile)
    if (collapsible === "none") {
      return (
        <div
          data-state="expanded" // For "none", visual state is always expanded
          data-variant={variant}
          className={cn(
            "hidden h-full md:flex md:flex-col", // Default: hidden on mobile, flex on desktop
            variant === "sidebar" && !(className?.includes("border")) && "border-r", // Only add border-r if not already in className
            variant === "floating" && "m-4 rounded-lg border bg-background shadow-lg",
            variant === "inset" && "bg-background",
            "w-[var(--sidebar-width)]", // Always full desktop width
            className
          )}
          ref={ref}
          {...props}
        >
          {React.Children.map(children, (child) => {
            if (React.isValidElement(child) && child.type === SidebarContent) {
              return React.cloneElement(child as React.ReactElement<SidebarContentProps>,
                {
                  isIconOnly: false, // Content is never icon-only
                }
              );
            }
            return child;
          })}
        </div>
      );
    }

    // 2. Handle mobile-specific behaviors
    if (isMobile) {
      if (collapsible === "offcanvas") {
        return (
          <Dialog open={state === "expanded"} onOpenChange={setOpen}>
            <DialogOverlay className="md:hidden" />
            <DialogContent
              side="left"
              className={cn(
                "h-full w-[var(--sidebar-width-mobile)] p-0 md:hidden",
                className
              )}
            >
              {React.Children.map(children, (child) => {
                if (React.isValidElement(child) && child.type === SidebarContent) {
                  return React.cloneElement(child as React.ReactElement<SidebarContentProps>,
                    {
                      isIconOnly: false,
                    }
                  );
                }
                return child;
              })}
            </DialogContent>
          </Dialog>
        );
      } else if (collapsible === "icon") {
        // Mobile "icon" collapsible: Renders INLINE, not as an overlay
        const widthClass = state === "expanded" ? "w-[var(--sidebar-mobile-expanded-inline-width)]" : "w-[var(--sidebar-width-icon)]";
        const isContentIconOnly = state === "collapsed";
        return (
          <div
            data-state={state}
            data-variant={variant}
            className={cn(
              "h-full flex flex-col", // Always present and flex column on mobile for 'icon' type
              "transition-all duration-300 ease-in-out", // Smooth width changes
              variant === "sidebar" && !(className?.includes("border")) && "border-r", // Only add border-r if not already in className
              variant === "floating" && "m-4 rounded-lg border bg-background shadow-lg",
              variant === "inset" && "bg-background",
              widthClass,
              className
            )}
            ref={ref}
            {...props}
          >
            {React.Children.map(children, (child) => {
              if (React.isValidElement(child) && child.type === SidebarContent) {
                return React.cloneElement(child as React.ReactElement<SidebarContentProps>,
                  {
                    isIconOnly: isContentIconOnly,
                  }
                );
              }
              return child;
            })}
          </div>
        );
      }
    }

    // 3. Desktop behavior (collapsible "icon" or "offcanvas" are both treated as inline)
    // This block is reached if !isMobile
    const widthClass = state === "expanded" ? "w-[var(--sidebar-width)]" : "w-[var(--sidebar-width-icon)]";
    const isContentIconOnly = state === "collapsed";

    return (
      <div
        data-state={state}
        data-variant={variant}
        className={cn(
          "hidden h-full md:flex md:flex-col", // Standard desktop visibility
          "transition-all duration-300 ease-in-out", // Smooth width changes
          variant === "sidebar" && !(className?.includes("border")) && "border-r", // Only add border-r if not already in className
          variant === "floating" && "m-4 rounded-lg border bg-background shadow-lg",
          variant === "inset" && "bg-background",
          widthClass,
          className
        )}
        ref={ref}
        {...props}
      >
        {React.Children.map(children, (child) => {
          if (React.isValidElement(child) && child.type === SidebarContent) {
            return React.cloneElement(child as React.ReactElement<SidebarContentProps>,
              {
                isIconOnly: isContentIconOnly,
              }
            );
          }
          return child;
        })}
      </div>
    );
  }
);
Sidebar.displayName = "Sidebar"

const SidebarTrigger = React.forwardRef<
  React.ElementRef<typeof Button>,
  React.ComponentProps<typeof Button>
>(({ className, onClick, children, ...props }, ref) => { // Explicitly destructure children
  const { toggleSidebar } = useSidebar()

  return (
    <Button
      ref={ref}
      data-sidebar="trigger"
      variant="ghost"
      size="icon"
      className={cn(
        "border-2 border-black bg-white hover:bg-yellow-300 transition-colors", // Removed h-8 w-8
        className
      )}
      onClick={(event) => {
        onClick?.(event)
        toggleSidebar()
      }}
      aria-label="Toggle sidebar" // Added for accessibility
      {...props}
    >
      {children || <PanelLeft className="h-5 w-5" />}
    </Button>
  )
})
SidebarTrigger.displayName = "SidebarTrigger"

const SidebarRail = React.forwardRef<
  HTMLButtonElement,
  React.ComponentProps<"button">
>(({ className, ...props }, ref) => {
  const { toggleSidebar } = useSidebar()

  return (
    <button
      ref={ref}
      data-sidebar="rail"
      aria-label="Toggle Sidebar"
      tabIndex={-1}
      onClick={toggleSidebar}
      title="Toggle Sidebar"
      className={cn(
        "absolute inset-y-0 z-20 hidden w-4 -translate-x-1/2 transition-all ease-linear after:absolute after:inset-y-0 after:left-1/2 after:w-[2px] hover:after:bg-black group-data-[collapsible=offcanvas]:translate-x-0 group-data-[collapsible=offcanvas]:opacity-100 group-data-[collapsible=icon]:hidden md:flex",
        "[[data-side=left]_&]:right-0 [[data-side=right]_&]:left-0",
        className
      )}
      {...props}
    />
  )
})
SidebarRail.displayName = "SidebarRail"

const SidebarInset = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div">
>(({ className, style: styleProp, ...props }, ref) => {
  const style = {
    ...styleProp,
  };

  return (
    <div
      ref={ref}
      data-sidebar="content"
      className={cn("flex-1", className)} // Base styling, padding handled by style prop
      style={style}
      {...props}
    />
  )
})
SidebarInset.displayName = "SidebarInset"

const SidebarInput = React.forwardRef<
  HTMLInputElement,
  React.ComponentProps<"input">
>(({ className, ...props }, ref) => {
  return (
    <input
      ref={ref}
      data-sidebar="input"
      className={cn(
        "flex h-8 w-full rounded-md border-2 border-black bg-white px-3 py-1 text-sm shadow-[2px_2px_0px_0px_#000] transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-gray-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    />
  )
})
SidebarInput.displayName = "SidebarInput"

const SidebarHeader = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div">
>(({ className, ...props }, ref) => {
  return (
    <div
      ref={ref}
      data-sidebar="header"
      className={cn("flex flex-col gap-2 p-4 border-b-4 border-black", className)}
      {...props}
    />
  )
})
SidebarHeader.displayName = "SidebarHeader"

const SidebarFooter = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div">
>(({ className, ...props }, ref) => {
  return (
    <div
      ref={ref}
      data-sidebar="footer"
      className={cn("flex flex-col gap-2 p-4 border-t-4 border-black", className)}
      {...props}
    />
  )
})
SidebarFooter.displayName = "SidebarFooter"

const SidebarSeparator = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div">
>(({ className, ...props }, ref) => {
  return (
    <div
      ref={ref}
      data-sidebar="separator"
      className={cn("mx-2 w-auto h-1 bg-black", className)}
      {...props}
    />
  )
})
SidebarSeparator.displayName = "SidebarSeparator"

const SidebarContent = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div"> & {
    isIconOnly?: boolean
  }
>(({ className, isIconOnly = false, ...props }, ref) => {
  return (
    <div
      ref={ref}
      data-sidebar="content"
      className={cn(
        "flex min-h-0 flex-1 flex-col gap-2 overflow-auto group-data-[collapsible=icon]:overflow-hidden",
        isIconOnly && "group-data-[collapsible=icon]:overflow-hidden",
        className
      )}
      {...props}
    />
  )
})
SidebarContent.displayName = "SidebarContent"

const SidebarGroup = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div">
>(({ className, ...props }, ref) => {
  return (
    <div
      ref={ref}
      data-sidebar="group"
      className={cn("relative flex w-full min-w-0 flex-col p-2", className)}
      {...props}
    />
  )
})
SidebarGroup.displayName = "SidebarGroup"

const SidebarGroupLabel = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div"> & {
    asChild?: boolean
  }
>(({ className, asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot : "div"

  return (
    <Comp
      ref={ref}
      data-sidebar="group-label"
      className={cn(
        "duration-200 flex h-8 shrink-0 items-center rounded-md px-2 text-xs font-bold uppercase tracking-wider text-black/70 outline-none ring-black transition-[margin,opa] ease-linear focus-visible:ring-2 [&>svg]:size-4 [&>svg]:shrink-0",
        "group-data-[collapsible=icon]:-mt-8 group-data-[collapsible=icon]:opacity-0",
        className
      )}
      {...props}
    />
  )
})
SidebarGroupLabel.displayName = "SidebarGroupLabel"

const SidebarGroupAction = React.forwardRef<
  HTMLButtonElement,
  React.ComponentProps<"button"> & {
    asChild?: boolean
  }
>(({ className, asChild = false, ...props }, ref) => {
  const Comp = asChild ? Slot : "button"

  return (
    <Comp
      ref={ref}
      data-sidebar="group-action"
      className={cn(
        "absolute right-3 top-3.5 flex aspect-square w-5 items-center justify-center rounded-md p-0 text-black outline-none ring-black transition-transform hover:bg-yellow-300 focus-visible:ring-2 [&>svg]:size-4 [&>svg]:shrink-0",
        // Increases the hit area of the button on mobile.
        "after:absolute after:-inset-2 after:md:hidden",
        "group-data-[collapsible=icon]:hidden",
        className
      )}
      {...props}
    />
  )
})
SidebarGroupAction.displayName = "SidebarGroupAction"

const SidebarGroupContent = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div">
>(({ className, ...props }, ref) => {
  return (
    <div
      ref={ref}
      data-sidebar="group-content"
      className={cn("w-full text-sm", className)}
      {...props}
    />
  )
})
SidebarGroupContent.displayName = "SidebarGroupContent"

const SidebarMenu = React.forwardRef<
  HTMLUListElement,
  React.ComponentProps<"ul">
>(({ className, ...props }, ref) => {
  return (
    <ul
      ref={ref}
      data-sidebar="menu"
      className={cn("flex w-full min-w-0 flex-col gap-1", className)}
      {...props}
    />
  )
})
SidebarMenu.displayName = "SidebarMenu"

const SidebarMenuItem = React.forwardRef<
  HTMLLIElement,
  React.ComponentProps<"li">
>(({ className, ...props }, ref) => {
  return (
    <li
      ref={ref}
      data-sidebar="menu-item"
      className={cn("group/menu-item relative", className)}
      {...props}
    />
  )
})
SidebarMenuItem.displayName = "SidebarMenuItem"

const sidebarMenuButtonVariants = cva(
  "peer/menu-button flex w-full items-center gap-2 overflow-hidden rounded-md p-2 text-left text-sm outline-none ring-black transition-[width,height,padding] hover:bg-yellow-300 focus-visible:ring-2 active:bg-yellow-400 disabled:pointer-events-none disabled:opacity-50 group-has-[[data-sidebar=menu-action]]/menu-item:pr-8 aria-disabled:pointer-events-none aria-disabled:opacity-50 data-[active=true]:bg-yellow-300 data-[active=true]:font-bold data-[state=open]:hover:bg-yellow-300 data-[state=open]:bg-yellow-300 group-data-[collapsible=icon]:!size-8 group-data-[collapsible=icon]:!p-2 [&>span:last-child]:truncate [&>svg]:size-4 [&>svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "hover:bg-yellow-300 hover:text-black",
        outline:
          "bg-white shadow-[2px_2px_0px_0px_#000] border-2 border-black hover:bg-yellow-300 hover:text-black",
      },
      size: {
        default: "h-8 text-sm",
        sm: "h-7 text-xs",
        lg: "h-12 text-sm group-data-[collapsible=icon]:!size-8",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

const SidebarMenuButton = React.forwardRef<
  HTMLButtonElement,
  React.ComponentProps<"button"> & {
    asChild?: boolean
    isActive?: boolean
    tooltip?: string | React.ComponentProps<typeof _TooltipContent>
  } & VariantProps<typeof sidebarMenuButtonVariants>
>(
  (
    {
      asChild = false,
      isActive = false,
      variant = "default",
      size = "default",
      tooltip,
      className,
      ...props
    },
    ref
  ) => {
    const Comp = asChild ? Slot : "button"

    const button = (
      <Comp
        ref={ref}
        data-sidebar="menu-button"
        data-size={size}
        data-active={isActive}
        className={cn(sidebarMenuButtonVariants({ variant, size }), className)}
        {...props}
      />
    )

    if (!tooltip) {
      return button
    }

    if (typeof tooltip === "string") {
      tooltip = {
        children: tooltip,
      }
    }

    return button
  }
)
SidebarMenuButton.displayName = "SidebarMenuButton"

const SidebarMenuAction = React.forwardRef<
  HTMLButtonElement,
  React.ComponentProps<"button"> & {
    asChild?: boolean
    showOnHover?: boolean
  }
>(({ className, asChild = false, showOnHover = false, ...props }, ref) => {
  const Comp = asChild ? Slot : "button"

  return (
    <Comp
      ref={ref}
      data-sidebar="menu-action"
      className={cn(
        "absolute right-1 top-1.5 flex aspect-square w-5 items-center justify-center rounded-md p-0 text-black outline-none ring-black transition-transform hover:bg-yellow-300 focus-visible:ring-2 peer-hover/menu-button:text-black [&>svg]:size-4 [&>svg]:shrink-0",
        // Increases the hit area of the button on mobile.
        "after:absolute after:-inset-2 after:md:hidden",
        "peer-data-[size=sm]/menu-button:top-1",
        "peer-data-[size=default]/menu-button:top-1.5",
        "peer-data-[size=lg]/menu-button:top-2.5",
        "group-data-[collapsible=icon]:hidden",
        showOnHover &&
          "group-focus-within/menu-item:opacity-100 group-hover/menu-item:opacity-100 data-[state=open]:opacity-100 peer-data-[active=true]/menu-button:text-black md:opacity-0",
        className
      )}
      {...props}
    />
  )
})
SidebarMenuAction.displayName = "SidebarMenuAction"

const SidebarMenuBadge = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div">
>(({ className, ...props }, ref) => {
  return (
    <div
      ref={ref}
      data-sidebar="menu-badge"
      className={cn(
        "absolute right-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-red-500 px-1 text-xs font-bold text-white border-2 border-black shadow-[2px_2px_0px_0px_#000]",
        "peer-hover/menu-button:text-white peer-data-[active=true]/menu-button:text-white",
        "peer-data-[size=sm]/menu-button:top-1",
        "peer-data-[size=default]/menu-button:top-1.5",
        "peer-data-[size=lg]/menu-button:top-2.5",
        "group-data-[collapsible=icon]:hidden",
        className
      )}
      {...props}
    />
  )
})
SidebarMenuBadge.displayName = "SidebarMenuBadge"

const SidebarMenuSkeleton = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div"> & {
    showIcon?: boolean
  }
>(({ className, showIcon = false, ...props }, ref) => {
  // Random width between 50 to 90%.
  const width = React.useMemo(() => {
    return `${Math.floor(Math.random() * 40) + 50}%`
  }, [])

  return (
    <div
      ref={ref}
      data-sidebar="menu-skeleton"
      className={cn("rounded-md h-8 flex gap-2 px-2 items-center", className)}
      {...props}
    >
      {showIcon && (
        <div className="flex h-4 w-4 rounded-md bg-gray-200 border border-black" />
      )}
      <div
        className="h-4 flex-1 max-w-[--skeleton-width] rounded-md bg-gray-200 border border-black"
        style={
          {
            "--skeleton-width": width,
          } as React.CSSProperties
        }
      />
    </div>
  )
})
SidebarMenuSkeleton.displayName = "SidebarMenuSkeleton"

const SidebarMenuSub = React.forwardRef<
  HTMLUListElement,
  React.ComponentProps<"ul">
>(({ className, ...props }, ref) => {
  return (
    <ul
      ref={ref}
      data-sidebar="menu-sub"
      className={cn(
        "mx-3.5 flex min-w-0 translate-x-px flex-col gap-1 border-l-2 border-black px-2.5 py-0.5",
        "group-data-[collapsible=icon]:hidden",
        className
      )}
      {...props}
    />
  )
})
SidebarMenuSub.displayName = "SidebarMenuSub"

const SidebarMenuSubItem = React.forwardRef<
  HTMLLIElement,
  React.ComponentProps<"li">
>(({ ...props }, ref) => {
  return <li ref={ref} {...props} />
})
SidebarMenuSubItem.displayName = "SidebarMenuSubItem"

const SidebarMenuSubButton = React.forwardRef<
  HTMLAnchorElement,
  React.ComponentProps<"a"> & {
    asChild?: boolean
    size?: "sm" | "md"
    isActive?: boolean
  }
>(({ asChild = false, size = "md", isActive, className, ...props }, ref) => {
  const Comp = asChild ? Slot : "a"

  return (
    <Comp
      ref={ref}
      data-sidebar="menu-sub-button"
      data-size={size}
      data-active={isActive}
      className={cn(
        "flex h-7 min-w-0 -translate-x-px items-center gap-2 overflow-hidden rounded-md px-2 text-black outline-none ring-black hover:bg-yellow-300 focus-visible:ring-2 active:bg-yellow-400 disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50 [&>span:last-child]:truncate [&>svg]:size-4 [&>svg]:shrink-0 [&>svg]:text-black",
        "data-[active=true]:bg-yellow-300 data-[active=true]:text-black",
        size === "sm" && "text-xs",
        size === "md" && "text-sm",
        "group-data-[collapsible=icon]:hidden",
        className
      )}
      {...props}
    />
  )
})
SidebarMenuSubButton.displayName = "SidebarMenuSubButton"

// Dummy TooltipContent component since we don't have tooltip installed
function _TooltipContent({ children }: { children: React.ReactNode }) {
  return <div>{children}</div>
}

export {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInput,
  SidebarInset,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSkeleton,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  SidebarProvider,
  SidebarRail,
  SidebarSeparator,
  SidebarTrigger,
  useSidebar,
}
