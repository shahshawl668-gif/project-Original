"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { EyeOff, Loader2, ShieldAlert } from "lucide-react";

import { fetchActiveSupport, revokeSupport, timeLeft } from "@/lib/support";

/**
 * Someone outside your company can read your payroll right now.
 *
 * Shown to every member, not just owners: whoever the payroll belongs to should
 * be told, not only whoever can change the setting. Deliberately impossible to
 * dismiss — a notice you can click away is one people learn to click away.
 */
export function SupportBanner() {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: ["support-active"],
    queryFn: fetchActiveSupport,
    // A session is time-boxed and revocable, so a stale banner is a lie in
    // either direction. Cheap call, checked often.
    refetchInterval: 60_000,
    retry: false,
  });

  const revoke = useMutation({
    mutationFn: revokeSupport,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["support-active"] }),
  });

  const grants = data?.active ?? [];
  if (grants.length === 0) return null;

  return (
    <div className="space-y-2">
      {grants.map((grant) => {
        const pending = grant.state === "pending";
        return (
          <div
            key={grant.id}
            className={
              pending
                ? "flex flex-wrap items-start gap-3 border-b border-warning-300/70 bg-warning-50 px-4 py-2.5 dark:border-warning-500/30 dark:bg-warning-500/10"
                : "flex flex-wrap items-start gap-3 border-b border-danger-300/70 bg-danger-50 px-4 py-2.5 dark:border-danger-500/30 dark:bg-danger-500/10"
            }
          >
            {pending ? (
              <ShieldAlert
                size={16}
                className="mt-0.5 shrink-0 text-warning-700 dark:text-warning-300"
              />
            ) : (
              <EyeOff size={16} className="mt-0.5 shrink-0 text-danger-700 dark:text-danger-300" />
            )}

            <div className="min-w-0 flex-1">
              <p
                className={
                  pending
                    ? "text-sm font-semibold text-warning-900 dark:text-warning-200"
                    : "text-sm font-semibold text-danger-800 dark:text-danger-200"
                }
              >
                {pending
                  ? `${grant.admin_email} has asked for read-only support access`
                  : `${grant.admin_email} can read this organization right now`}
                <span className="ml-2 font-normal opacity-80">{timeLeft(grant.expires_at)}</span>
              </p>
              <p className="text-xs text-ink-700 dark:text-ink-300">
                &ldquo;{grant.reason}&rdquo; — read-only, employee identities masked.
              </p>
            </div>

            <button
              type="button"
              onClick={() => revoke.mutate(grant.id)}
              disabled={revoke.isPending}
              className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg border border-ink-300 bg-white px-2.5 text-xs font-semibold text-ink-800 transition hover:bg-ink-50 disabled:opacity-50 dark:border-ink-600 dark:bg-ink-900 dark:text-ink-100"
            >
              {revoke.isPending && <Loader2 size={12} className="animate-spin" />}
              {pending ? "Decline" : "End it now"}
            </button>
          </div>
        );
      })}
    </div>
  );
}
