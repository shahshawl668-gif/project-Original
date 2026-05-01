import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-slate-200/80", className)}
      {...props}
    />
  );
}

export function StatCardSkeleton() {
  return (
    <div className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-sm ring-1 ring-slate-900/[0.04]">
      <Skeleton className="mb-4 h-9 w-9 rounded-lg" />
      <Skeleton className="mb-2 h-8 w-20" />
      <Skeleton className="h-3 w-28" />
      <Skeleton className="mt-2 h-3 w-36" />
    </div>
  );
}
