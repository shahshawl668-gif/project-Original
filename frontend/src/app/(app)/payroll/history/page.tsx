"use client";

export const dynamic = "force-dynamic";

import { Suspense } from "react";
import RegisterHistoryContent from "./RegisterHistoryContent";

export default function RegisterHistoryPage() {
  return (
    <Suspense fallback={<div className="p-6">Loading...</div>}>
      <RegisterHistoryContent />
    </Suspense>
  );
}
