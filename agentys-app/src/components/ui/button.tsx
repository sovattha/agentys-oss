/* eslint-disable react-refresh/only-export-components */
import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

// NOTE: variants are wired to the Agentys design tokens declared in the
// index.css `@theme` block (accent-primary, content-*, border-default,
// surface-*, error) — NOT the stock shadcn token names (primary, background,
// destructive, ring), which are intentionally not registered in this project.
// `default` = canonical filled-accent Save/Confirm button.
// `outline`  = canonical transparent + 1px border Cancel button.
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-all cursor-pointer disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 shrink-0 [&_svg]:shrink-0 outline-none focus-visible:border-accent-primary focus-visible:ring-accent-primary/50 focus-visible:ring-[3px] aria-invalid:ring-error/30 aria-invalid:border-error",
  {
    variants: {
      variant: {
        default: "bg-accent-primary text-content-inverse shadow-sm",
        destructive:
          "bg-error text-content-inverse focus-visible:ring-error/40",
        outline:
          "border border-border-strong bg-transparent text-content-secondary shadow-xs",
        secondary: "bg-surface-secondary text-content-secondary",
        ghost: "text-content-secondary",
        link: "text-accent-primary underline-offset-4",
      },
      size: {
        default: "h-9 px-4 py-2 has-[>svg]:px-3",
        sm: "h-8 rounded-md gap-1.5 px-3 has-[>svg]:px-2.5",
        lg: "h-10 rounded-md px-6 has-[>svg]:px-4",
        icon: "size-9",
        "icon-sm": "size-8",
        "icon-lg": "size-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
