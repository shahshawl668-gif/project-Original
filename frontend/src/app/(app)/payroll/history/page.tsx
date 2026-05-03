"use client";

import { Suspense } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { Card } from "@/components/ui/card";
import RegisterHistoryContent from "./RegisterHistoryContent";

function RegisterHistoryFallback() {
  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-4 max-w-xl" />
        </div>
        <Skeleton className="h-10 w-36 rounded-xl sm:mt-0" />
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="overflow-hidden">
          <div className="space-y-0 border-b border-ink-100 p-4 dark:border-white/[0.06]">
            <Skeleton className="mx-auto mb-5 h-3 w-32" />
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="flex items-center gap-3 px-2 py-3">
                <Skeleton className="h-10 w-10 rounded-xl" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-28" />
                  <Skeleton className="h-3 w-20" />
                </div>
              </div>
            ))}
          </div>
        </Card>
        <Card className="min-h-[22rem] overflow-hidden lg:col-span-2">
          <div className="flex h-full flex-col items-center justify-center gap-4 p-10">
            <Skeleton className="h-14 w-14 rounded-2xl" />
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-3 w-52" />
          </div>
        </Card>
      </div>
    </div>
  );
}

/** `useSearchParams()` must be under Suspense for Next.js App Router production builds (e.g. Vercel). */
export default function RegisterHistoryPage() {
  return (
    <Suspense fallback={<RegisterHistoryFallback />}>
      <RegisterHistoryContent />
    </Suspense>
  );
}
