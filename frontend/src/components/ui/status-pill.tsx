import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger" | "running";

const TONES: Record<StatusTone, { wrap: string; dot: string }> = {
  neutral: { wrap: "border-ink-200 bg-ink-50 text-ink-700", dot: "bg-ink-400" },
  info: { wrap: "border-brand-200 bg-brand-50 text-brand-800", dot: "bg-brand-500" },
  success: { wrap: "border-success-200 bg-success-50 text-success-800", dot: "bg-success-600" },
  warning: { wrap: "border-warning-200 bg-warning-50 text-warning-900", dot: "bg-warning-500" },
  danger: { wrap: "border-danger-200 bg-danger-50 text-danger-800", dot: "bg-danger-600" },
  running: { wrap: "border-brand-200 bg-brand-50 text-brand-800", dot: "bg-brand-500 animate-pulse-soft" },
};

/**
 * A state, said in words with a coloured dot beside it. The words carry the
 * meaning; the colour only helps it be found.
 */
export function StatusPill({
  tone = "neutral",
  children,
  className,
  size = "default",
}: {
  tone?: StatusTone;
  children: ReactNode;
  className?: string;
  size?: "default" | "lg";
}) {
  const t = TONES[tone];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border font-medium",
        size === "lg" ? "px-2.5 py-1 text-[13px]" : "px-2 py-0.5 text-xs",
        t.wrap,
        className,
      )}
    >
      <span className={cn("h-1.5 w-1.5 flex-shrink-0 rounded-full", t.dot)} aria-hidden />
      {children}
    </span>
  );
}
