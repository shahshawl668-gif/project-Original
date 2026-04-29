"use client";

import { Suspense } from "react";
import RegisterHistoryContent from "./RegisterHistoryContent";

function RegisterHistoryFallback() {
  return (
    <div className="space-y-6 max-w-7xl animate-pulse">
      <div className="h-10 bg-slate-100 rounded w-48" />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-white h-80" />
        <div className="lg:col-span-2 rounded-xl border border-slate-200 bg-white h-80" />
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
