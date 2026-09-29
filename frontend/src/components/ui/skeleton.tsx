import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/** A placeholder with the shape of what is coming. It pulses; it does not sweep. */
export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden className={cn("animate-pulse-soft rounded-md bg-ink-100", className)} {...props} />;
}

export function StatCardSkeleton() {
  return (
    <div className="rounded-xl border border-ink-200 bg-white p-4">
      <Skeleton className="mb-3 h-3 w-24" />
      <Skeleton className="mb-2 h-6 w-20" />
      <Skeleton className="h-3 w-32" />
    </div>
  );
}

/** Rows for a table that is loading, at the density the table will have. */
export function TableSkeleton({ rows = 8, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div className="divide-y divide-ink-100" role="status" aria-label="Loading">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex items-center gap-4 px-3 py-2.5">
          {Array.from({ length: cols }).map((__, c) => (
            <Skeleton key={c} className={cn("h-3", c === 0 ? "w-40" : "flex-1")} />
          ))}
        </div>
      ))}
    </div>
  );
}
