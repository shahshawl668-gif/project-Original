"use client";

import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

/**
 * True once something has been loading long enough to need explaining.
 *
 * A spinner says "working". It does not say "this is normal", and after ten
 * seconds people stop believing it. On a host that suspends idle instances the
 * first request of the morning can take the better part of a minute, which is
 * indistinguishable from a hang unless the page says otherwise.
 */
export function useSlowRequest(isLoading: boolean, afterMs = 6000): boolean {
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    if (!isLoading) {
      setSlow(false);
      return;
    }
    const timer = window.setTimeout(() => setSlow(true), afterMs);
    return () => window.clearTimeout(timer);
  }, [isLoading, afterMs]);

  return slow;
}

/** The line itself. Renders nothing until the wait is actually unusual. */
export function SlowRequestNotice({
  isLoading,
  afterMs = 6000,
  className = "",
}: {
  isLoading: boolean;
  afterMs?: number;
  className?: string;
}) {
  const slow = useSlowRequest(isLoading, afterMs);
  if (!slow) return null;

  return (
    <p
      role="status"
      aria-live="polite"
      className={`flex items-center gap-2 text-xs text-ink-500 dark:text-ink-400 ${className}`}
    >
      <Loader2 size={13} className="animate-spin" aria-hidden />
      <span>
        Still waiting on the server. The first request after a quiet spell can take up to a
        minute while it starts back up — after that it is quick.
      </span>
    </p>
  );
}
