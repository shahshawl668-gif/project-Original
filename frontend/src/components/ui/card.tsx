import * as React from "react";
import { cn } from "@/lib/utils";

export const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        "rounded-2xl border border-ink-200/70 bg-white shadow-soft ring-1 ring-ink-900/[0.03]",
        "dark:border-white/[0.07] dark:bg-ink-900/70 dark:ring-white/[0.03] dark:shadow-[0_1px_0_rgba(0,0,0,0.4),0_16px_40px_rgba(0,0,0,0.45)]",
        className,
      )}
      {...props}
    />
  ),
);
Card.displayName = "Card";

export const CardHeader = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex flex-col gap-1 border-b border-ink-100 p-5 dark:border-white/[0.06]",
      className,
    )}
    {...props}
  />
);

export const CardTitle = ({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
  <h3
    className={cn(
      "font-display text-base font-semibold tracking-tight text-ink-900 dark:text-white",
      className,
    )}
    {...props}
  />
);

export const CardDescription = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLParagraphElement>) => (
  <p className={cn("text-sm text-ink-500 dark:text-ink-300", className)} {...props} />
);

export const CardContent = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("p-5", className)} {...props} />
);

export const CardFooter = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex items-center justify-end gap-2 border-t border-ink-100 p-5 dark:border-white/[0.06]",
      className,
    )}
    {...props}
  />
);
