"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError } from "@/lib/api";

/**
 * Retry the failures a retry can fix, and none of the others.
 *
 * A 401 is not going to become a 200 by asking again — it just doubles how
 * long a signed-out page sits spinning before it admits what is wrong. The
 * same goes for a 403 or a 404. A 5xx or a dropped connection is worth one
 * more attempt, which is what carries a request through a server that is
 * still starting up.
 */
function retry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
    return false;
  }
  return failureCount < 1;
}

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60_000,
            refetchOnWindowFocus: false,
            retry,
          },
        },
      })
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
