import { Check, X } from "lucide-react";
import { cn } from "@/lib/utils";

export type StepState = "done" | "current" | "error" | "todo";
export type Step = { label: string; state: StepState; note?: string };

/**
 * Where a multi-step job stands. Each step states itself in words for screen
 * readers; the colour and the tick only repeat it.
 */
export function Stepper({ steps, className, label }: { steps: Step[]; className?: string; label: string }) {
  return (
    <ol aria-label={label} className={cn("flex flex-wrap items-center gap-x-2 gap-y-2", className)}>
      {steps.map((s, i) => (
        <li key={s.label} className="flex min-w-0 items-center gap-2" aria-current={s.state === "current" ? "step" : undefined}>
          <span
            className={cn(
              "flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full text-[11px] font-semibold",
              s.state === "done" && "bg-success-600 text-white",
              s.state === "current" && "bg-brand-600 text-white",
              s.state === "error" && "bg-danger-600 text-white",
              s.state === "todo" && "border border-ink-200 bg-white text-ink-400",
            )}
            aria-hidden
          >
            {s.state === "done" ? <Check size={13} strokeWidth={3} /> : s.state === "error" ? <X size={13} strokeWidth={3} /> : i + 1}
          </span>
          <span className="min-w-0">
            <span className={cn("block truncate text-[13px] font-medium", s.state === "todo" ? "text-ink-400" : "text-ink-900")}>
              <span className="sr-only">
                {s.state === "done" ? "Completed: " : s.state === "current" ? "Current: " : s.state === "error" ? "Failed: " : "Not started: "}
              </span>
              {s.label}
            </span>
            {s.note ? <span className="block truncate text-xs text-ink-500">{s.note}</span> : null}
          </span>
          {i < steps.length - 1 ? <span className="mx-1 hidden h-px w-8 bg-ink-200 sm:block" aria-hidden /> : null}
        </li>
      ))}
    </ol>
  );
}
