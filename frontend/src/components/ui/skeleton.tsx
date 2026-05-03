import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-md bg-ink-100/80 before:absolute before:inset-0 before:-translate-x-full before:bg-gradient-to-r before:from-transparent before:via-white/70 before:to-transparent before:animate-[shimmer_2s_linear_infinite]",
        className,
      )}
      style={{
        backgroundSize: "1000px 100%",
      }}
      {...props}
    />
  );
}

export function StatCardSkeleton() {
  return (
    <div className="rounded-2xl border border-ink-200/70 bg-white p-5 shadow-soft">
      <Skeleton className="mb-4 h-10 w-10 rounded-xl" />
      <Skeleton className="mb-2 h-9 w-24" />
      <Skeleton className="mb-1 h-3 w-32" />
      <Skeleton className="h-3 w-40" />
    </div>
  );
}
