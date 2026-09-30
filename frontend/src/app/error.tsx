"use client";

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error("App error boundary:", error);
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-ink-50 p-6">
      <div className="max-w-md rounded-2xl border border-ink-200 bg-white p-8 shadow-sm">
        <h1 className="text-lg font-semibold text-ink-900">Something went wrong.</h1>
        <p className="mt-2 text-sm text-ink-600">
          {error.message || "An unexpected error occurred while rendering this page."}
        </p>
        {error.digest ? (
          <p className="mt-2 text-xs text-ink-500">Reference: {error.digest}</p>
        ) : null}
        <div className="mt-5 flex gap-3">
          <button
            type="button"
            onClick={reset}
            className="rounded-xl bg-ink-900 px-4 py-2 text-sm font-medium text-white hover:bg-ink-800"
          >
            Try again
          </button>
          <a
            href="/dashboard"
            className="rounded-xl border border-ink-200 px-4 py-2 text-sm font-medium text-ink-700 hover:bg-ink-50"
          >
            Go to dashboard
          </a>
        </div>
      </div>
    </div>
  );
}
