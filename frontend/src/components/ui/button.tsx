"use client";

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-semibold transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-1 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default:
          "bg-gradient-to-br from-brand-600 to-accent-600 text-white shadow-soft hover:shadow-glow hover:from-brand-500 hover:to-accent-500",
        primary:
          "bg-gradient-to-br from-brand-600 to-accent-600 text-white shadow-soft hover:shadow-glow",
        solid: "bg-ink-900 text-white shadow-soft hover:bg-ink-800",
        destructive: "bg-danger-600 text-white shadow-soft hover:bg-danger-700",
        outline:
          "border border-ink-200 bg-white text-ink-800 shadow-sm hover:bg-ink-50 hover:border-ink-300",
        secondary: "bg-ink-100 text-ink-900 hover:bg-ink-200",
        ghost: "text-ink-700 hover:bg-ink-100 hover:text-ink-900",
        link: "text-brand-700 underline-offset-4 hover:underline",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-8 px-3 text-xs",
        lg: "h-11 px-6 text-[15px]",
        xl: "h-12 px-7 text-[15px]",
        icon: "h-10 w-10",
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
