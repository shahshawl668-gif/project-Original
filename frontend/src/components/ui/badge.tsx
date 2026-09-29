import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/**
 * A label, not a button: sentence case, medium weight, a tint and a hairline
 * border. Colour carries the meaning; the text says it too, so the badge reads
 * the same to someone who cannot tell red from green.
 */
const badgeVariants = cva(
  "inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-px text-xs font-medium leading-5",
  {
    variants: {
      variant: {
        default: "border-brand-200 bg-brand-50 text-brand-800",
        primary: "border-brand-200 bg-brand-50 text-brand-800",
        secondary: "border-ink-200 bg-ink-50 text-ink-700",
        success: "border-success-200 bg-success-50 text-success-800",
        warning: "border-warning-200 bg-warning-50 text-warning-800",
        outline: "border-ink-200 bg-white text-ink-700",
        destructive: "border-danger-200 bg-danger-50 text-danger-800",
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
