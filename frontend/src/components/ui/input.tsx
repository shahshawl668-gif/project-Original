import * as React from "react";
import { cn } from "@/lib/utils";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type = "text", ...props }, ref) => (
    <input
      type={type}
      ref={ref}
      className={cn(
        "flex h-9 w-full rounded-lg border border-ink-200 bg-white px-3 py-1.5 text-[13px] text-ink-900 shadow-soft transition-colors hover:border-ink-300 placeholder:text-ink-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 disabled:cursor-not-allowed disabled:opacity-50 aria-[invalid=true]:border-danger-400 aria-[invalid=true]:ring-danger-500/20",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";
