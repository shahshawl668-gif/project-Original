"use client";

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/**
 * One primary action per view, in the action colour. Secondary actions are
 * outlined, tertiary are ghost. Destructive is red and never the default.
 */
const buttonVariants = cva(
  "inline-flex select-none items-center justify-center gap-1.5 whitespace-nowrap rounded-lg text-[13px] font-medium transition-colors duration-fast focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:pointer-events-none disabled:opacity-50 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-brand-600 text-white shadow-soft hover:bg-brand-700 active:bg-brand-800",
        primary: "bg-brand-600 text-white shadow-soft hover:bg-brand-700 active:bg-brand-800",
        solid: "bg-ink-900 text-white shadow-soft hover:bg-ink-800",
        destructive: "bg-danger-600 text-white shadow-soft hover:bg-danger-700",
        "destructive-outline":
          "border border-danger-200 bg-white text-danger-700 hover:border-danger-300 hover:bg-danger-50",
        outline:
          "border border-ink-200 bg-white text-ink-800 shadow-soft hover:border-ink-300 hover:bg-ink-50",
        secondary: "bg-ink-100 text-ink-900 hover:bg-ink-200",
        ghost: "text-ink-700 hover:bg-ink-100 hover:text-ink-900",
        link: "h-auto px-0 text-brand-700 underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-3.5",
        sm: "h-8 px-2.5 text-xs",
        lg: "h-10 px-4 text-sm",
        xl: "h-11 px-5 text-sm",
        icon: "h-9 w-9",
        "icon-sm": "h-8 w-8",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
