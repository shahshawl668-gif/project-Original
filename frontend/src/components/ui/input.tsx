import * as React from "react";
import { cn } from "@/lib/utils";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type = "text", ...props }, ref) => (
    <input
      type={type}
      ref={ref}
      className={cn(
        "flex h-10 w-full rounded-lg border border-ink-200 bg-white px-3.5 py-1.5 text-sm text-ink-900 shadow-sm transition-colors placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-1 disabled:cursor-not-allowed disabled:opacity-50",
        "dark:border-white/10 dark:bg-white/[0.04] dark:text-white dark:placeholder:text-ink-500 dark:focus:ring-offset-ink-950",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";
