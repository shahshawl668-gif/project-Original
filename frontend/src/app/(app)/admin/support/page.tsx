"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Loader2, ShieldAlert } from "lucide-react";

import { Menu, MenuItem } from "@/components/cost/Menu";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import { formatWhen } from "@/lib/team";
import {
  endSupport,
  fetchMyGrants,
  fetchSupportOrgs,
  openSupport,
  timeLeft,
} from "@/lib/support";

const DURATIONS = [15, 30, 60, 120, 240, 480];

/**
 * Opening a break-glass session on a client's data.
 *
 * The page is built to make using it feel like what it is. The reason field is
 * long and mandatory because it is written to the client's own audit trail, and
 * the limits are stated on the page rather than discovered in a refusal.
 */
export default function SupportAccessPage() {
  const queryClient = useQueryClient();
  const [orgId, setOrgId] = useState("");
  const [reason, setReason] = useState("");
  const [minutes, setMinutes] = useState(60);
  const [error, setError] = useState<string | null>(null);

  const { data: orgs } = useQuery({ queryKey: ["support-orgs"], queryFn: fetchSupportOrgs });
  const { data: grants } = useQuery({ queryKey: ["support-grants"], queryFn: fetchMyGrants });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["support-grants"] });

  const open = useMutation({
    mutationFn: openSupport,
    onSuccess: () => {
      setError(null);
      setReason("");
      refresh();
    },
    onError: (err: Error) => setError(err.message),
  });

  const close = useMutation({
    mutationFn: ({ id, why }: { id: string; why: string }) => endSupport(id, why),
    onSuccess: refresh,
    onError: (err: Error) => setError(err.message),
  });

  const chosen = orgs?.find((o) => o.id === orgId);
  const live = (grants ?? []).filter((g) => g.state === "active" || g.state === "pending");
  const past = (grants ?? []).filter((g) => g.state !== "active" && g.state !== "pending");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Support access"
        description="Read a client's data to help them — time-boxed, reasoned, and visible to them."
      />

      {error && (
        <AlertBanner variant="error" title="That did not work">
          {error}
        </AlertBanner>
      )}

      <AlertBanner variant="warning" title="What a session is, and is not">
        Read-only, with employee identities masked — the same view a viewer at that client
        gets. It expires on its own, the client sees it the moment it opens, and they can
        end it instantly. Your reason goes into <strong>their</strong> audit trail, so write
        it for them to read.
      </AlertBanner>

      <Card>
        <CardContent className="space-y-4 py-5">
          <div className="flex flex-wrap items-end gap-3">
            <Menu
              label="Organization"
              summary={chosen ? chosen.name : "Choose one"}
              width="w-80"
            >
              {(closeMenu) => (
                <>
                  {(orgs ?? []).map((org) => (
                    <MenuItem
                      key={org.id}
                      selected={org.id === orgId}
                      hint={
                        org.support_access_policy === "disabled"
                          ? "Support access is switched off here"
                          : org.support_access_policy === "approval_required"
                            ? "An owner there must approve first"
                            : undefined
                      }
                      onClick={() => {
                        setOrgId(org.id);
                        closeMenu();
                      }}
                    >
                      {org.name}
                    </MenuItem>
                  ))}
                </>
              )}
            </Menu>

            <Menu label="Duration" summary={`${minutes} minutes`} width="w-56">
              {(closeMenu) => (
                <>
                  {DURATIONS.map((option) => (
                    <MenuItem
                      key={option}
                      selected={option === minutes}
                      onClick={() => {
                        setMinutes(option);
                        closeMenu();
                      }}
                    >
                      {option < 60 ? `${option} minutes` : `${option / 60} hours`}
                    </MenuItem>
                  ))}
                </>
              )}
            </Menu>
          </div>

          <div>
            <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wide text-ink-400">
              Why — the client reads this
            </span>
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={2}
              placeholder="Investigating ticket 412 — cost dashboard shows no June data"
              className="w-full rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900 placeholder:text-ink-400 dark:border-ink-700 dark:bg-ink-900 dark:text-white"
            />
            <p className="pt-1 text-[11px] text-ink-500 dark:text-ink-400">
              At least 12 characters. {reason.trim().length} so far.
            </p>
          </div>

          <button
            type="button"
            disabled={!orgId || reason.trim().length < 12 || open.isPending}
            onClick={() => open.mutate({ org_id: orgId, reason: reason.trim(), minutes })}
            className="inline-flex h-9 items-center gap-2 rounded-lg bg-danger-600 px-3 text-sm font-semibold text-white transition hover:bg-danger-700 disabled:opacity-50"
          >
            {open.isPending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <KeyRound size={14} />
            )}
            {chosen?.support_access_policy === "approval_required"
              ? "Request access"
              : "Open session"}
          </button>
        </CardContent>
      </Card>

      {live.length > 0 && (
        <Card>
          <CardContent className="py-5">
            <h3 className="flex items-center gap-2 pb-3 text-base font-semibold text-ink-900 dark:text-white">
              <ShieldAlert size={16} className="text-danger-500" /> Open right now
            </h3>
            <div className="divide-y divide-ink-200/70 dark:divide-ink-700/60">
              {live.map((grant) => (
                <div
                  key={grant.id}
                  className="flex flex-wrap items-center justify-between gap-2 py-3"
                >
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-ink-900 dark:text-white">
                      {grant.organization} · {grant.state} · {timeLeft(grant.expires_at)}
                    </p>
                    <p className="text-xs text-ink-500 dark:text-ink-400">
                      &ldquo;{grant.reason}&rdquo; · used {grant.use_count ?? 0} time(s)
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => close.mutate({ id: grant.id, why: "finished" })}
                    disabled={close.isPending}
                    className="inline-flex h-8 items-center rounded-lg border border-ink-200 px-2.5 text-xs font-semibold text-ink-700 transition hover:bg-ink-50 disabled:opacity-50 dark:border-ink-700 dark:text-ink-200 dark:hover:bg-ink-800"
                  >
                    End now
                  </button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="py-5">
          <h3 className="pb-3 text-base font-semibold text-ink-900 dark:text-white">
            Your past sessions
          </h3>
          {past.length ? (
            <div className="divide-y divide-ink-200/70 dark:divide-ink-700/60">
              {past.slice(0, 30).map((grant) => (
                <p key={grant.id} className="py-2 text-xs text-ink-500 dark:text-ink-400">
                  <span className="font-medium text-ink-700 dark:text-ink-200">
                    {grant.organization}
                  </span>{" "}
                  · {grant.state} · {formatWhen(grant.requested_at ?? null)} · used{" "}
                  {grant.use_count ?? 0} time(s) — &ldquo;{grant.reason}&rdquo;
                </p>
              ))}
            </div>
          ) : (
            <p className="text-sm text-ink-500 dark:text-ink-400">None yet.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
