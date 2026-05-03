import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type EmptyStateProps = {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
};

export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "relative flex flex-col items-center justify-center overflow-hidden rounded-2xl border border-dashed border-ink-200 bg-gradient-to-br from-white via-ink-50/40 to-white px-6 py-14 text-center",
        className,
      )}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute -top-20 left-1/2 h-40 w-40 -translate-x-1/2 rounded-full bg-gradient-to-br from-brand-200/40 to-accent-200/30 blur-3xl"
      />
      {icon ? (
        <div className="relative mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-white shadow-soft ring-1 ring-ink-900/[0.05]">
          {icon}
        </div>
      ) : null}
      <p className="relative font-display text-base font-semibold tracking-tight text-ink-900">
        {title}
      </p>
      {description ? (
        <p className="relative mt-1.5 max-w-sm text-sm leading-relaxed text-ink-500">{description}</p>
      ) : null}
      {action ? <div className="relative mt-5">{action}</div> : null}
    </div>
  );
}
