import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wide transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-gradient-to-br from-brand-600 to-accent-600 text-white",
        primary: "border-brand-200 bg-brand-50 text-brand-700",
        secondary: "border-ink-200 bg-ink-100 text-ink-700",
        success: "border-success-200 bg-success-50 text-success-700",
        warning: "border-warning-200 bg-warning-50 text-warning-700",
        outline: "border-ink-300 bg-white text-ink-700",
        destructive: "border-danger-200 bg-danger-50 text-danger-700",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { badgeVariants };
