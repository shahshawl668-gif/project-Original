"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BadgeCheck,
  Download,
  History,
  ShieldCheck,
  Trash2,
  UploadCloud,
} from "lucide-react";

import { Menu, MenuItem } from "@/components/cost/Menu";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchAudit } from "@/lib/cost-analysis";

const ACTIONS: { key: string | null; label: string }[] = [
  { key: null, label: "Everything" },
  { key: "register.uploaded", label: "Registers uploaded" },
  { key: "budget.uploaded", label: "Budgets uploaded" },
  { key: "budget.approved", label: "Budgets approved" },
  { key: "budget.deleted", label: "Drafts deleted" },
  { key: "report.downloaded", label: "Reports downloaded" },
];

const ICONS: Record<string, typeof UploadCloud> = {
  "register.uploaded": UploadCloud,
  "budget.uploaded": UploadCloud,
  "budget.approved": BadgeCheck,
  "budget.deleted": Trash2,
  "report.downloaded": Download,
};

function when(value: string | null): string {
  if (!value) return "—";
  const at = new Date(value);
  return at.toLocaleString("en-IN", {
    day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

/**
 * The audit trail.
 *
 * Months later, when a figure is challenged, the only useful answer is who
 * uploaded which file, when, and who approved it. Read-only by construction —
 * the API has no endpoint that edits or removes an event.
 */
export default function AuditPage() {
  const [action, setAction] = useState<string | null>(null);

  const trail = useQuery({
    queryKey: ["audit", action],
    queryFn: () => fetchAudit({ action: action ?? undefined, limit: 250 }),
  });

  const current = ACTIONS.find((a) => a.key === action) ?? ACTIONS[0];

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Governance"
        title="Audit trail"
        description="Every upload, approval and export, with who did it and when. Written in the same transaction as the change it describes, so a rolled-back change leaves no trace claiming it happened — and there is no endpoint that edits or removes an entry."
      />

      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 py-4">
          <div className="w-56">
            <Menu label="Show" icon={History} summary={current.label} width="w-56">
              {(close) =>
                ACTIONS.map((option) => (
                  <MenuItem
                    key={option.key ?? "all"}
                    selected={option.key === action}
                    onClick={() => { setAction(option.key); close(); }}
                  >
                    {option.label}
                  </MenuItem>
                ))
              }
            </Menu>
          </div>
          <p className="flex items-center gap-1.5 pb-2 text-xs text-ink-500 dark:text-ink-400">
            <ShieldCheck size={13} /> Scoped to this workspace. Other entities keep their own.
          </p>
        </CardContent>
      </Card>

      {trail.isError && (
        <AlertBanner variant="error" title="Could not load the trail">
          {(trail.error as Error).message}
        </AlertBanner>
      )}

      {trail.isLoading ? (
        <Skeleton className="h-64" />
      ) : !trail.data?.events.length ? (
        <EmptyState
          icon={History}
          title="Nothing recorded yet"
          description="Uploads, budget approvals and report downloads appear here as they happen."
        />
      ) : (
        <Card>
          <CardContent className="py-2">
            <ol className="divide-y divide-ink-100 dark:divide-white/5">
              {trail.data.events.map((event) => {
                const Icon = ICONS[event.action] ?? History;
                return (
                  <li key={event.id} className="flex items-start gap-3 py-3">
                    <span className="mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg bg-ink-100 text-ink-600 dark:bg-white/[0.07] dark:text-ink-300">
                      <Icon size={14} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-ink-900 dark:text-white">{event.summary}</p>
                      <p className="text-xs text-ink-500 dark:text-ink-400">
                        {event.user_email ?? "unknown user"} · {when(event.created_at)}
                        {event.detail?.masked === true && " · identities masked"}
                      </p>
                    </div>
                    <span className="flex-shrink-0 rounded-full bg-ink-100 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-ink-500 dark:bg-white/[0.06] dark:text-ink-400">
                      {event.action.split(".")[1] ?? event.action}
                    </span>
                  </li>
                );
              })}
            </ol>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
