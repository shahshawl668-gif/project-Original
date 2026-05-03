"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Plus, ShieldOff, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { apiJson } from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AlertBanner } from "@/components/ui/alert-banner";
import { EmptyState } from "@/components/ui/empty-state";

type Pref = { rule_id: string; suppressed: boolean };

export default function RulePreferencesPage() {
  const qc = useQueryClient();
  const [ruleId, setRuleId] = useState("");
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const list = useQuery({
    queryKey: ["rule-preferences"],
    queryFn: () => apiJson<Pref[]>("/api/rule-preferences"),
    enabled: mounted,
  });

  const upsert = useMutation({
    mutationFn: (body: { rule_id: string; suppressed: boolean }) =>
      apiJson("/api/rule-preferences", { method: "PUT", body: JSON.stringify(body) }),
    onSuccess: () => {
      toast.success("Preference saved");
      void qc.invalidateQueries({ queryKey: ["rule-preferences"] });
      setRuleId("");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const del = useMutation({
    mutationFn: (id: string) =>
      apiJson(`/api/rule-preferences/${encodeURIComponent(id)}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Removed");
      void qc.invalidateQueries({ queryKey: ["rule-preferences"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const add = () => {
    const rid = ruleId.trim();
    if (!rid) {
      toast.error("Enter a rule id (e.g. STAT-001, MOM-002)");
      return;
    }
    upsert.mutate({ rule_id: rid, suppressed: true });
  };

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Rule engine"
        title="Suppressed validation rules"
        description="Hide specific rule findings for your tenant after payroll validation and in Excel export summaries. This does not change statutory calculations — only the reported findings."
      />

      {list.isError && (
        <AlertBanner variant="error" title="Could not load preferences">
          {(list.error as Error).message}
        </AlertBanner>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <Card>
          <CardHeader>
            <p className="font-display text-[11px] font-bold uppercase tracking-[0.14em] text-ink-500 dark:text-ink-300">
              Add rule id
            </p>
            <CardTitle>Suppress a finding</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-col gap-2 sm:flex-row">
              <input
                value={ruleId}
                onChange={(e) => setRuleId(e.target.value)}
                placeholder="e.g. STAT-006"
                className="flex-1 rounded-xl border border-ink-200 bg-white px-3 py-2 font-mono text-sm text-ink-900 shadow-sm transition-colors placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-brand-500/40 dark:border-white/10 dark:bg-white/[0.04] dark:text-white dark:placeholder:text-ink-500"
              />
              <Button type="button" onClick={add} disabled={upsert.isPending}>
                <Plus size={15} strokeWidth={2.25} />
                Suppress
              </Button>
            </div>
            <p className="text-xs text-ink-500 dark:text-ink-400">
              Suppressed rules will be hidden from validation results but remain available for audit. Use rule ids
              like <code className="rounded bg-ink-100 px-1 py-0.5 font-mono text-[11px] text-ink-700 dark:bg-white/10 dark:text-ink-200">STAT-001</code>{" "}
              or <code className="rounded bg-ink-100 px-1 py-0.5 font-mono text-[11px] text-ink-700 dark:bg-white/10 dark:text-ink-200">MOM-002</code>.
            </p>
          </CardContent>
        </Card>

        <Card className="overflow-hidden">
          <div className="flex items-center gap-2 border-b border-ink-100 px-5 py-4 text-sm font-semibold text-ink-800 dark:border-white/[0.06] dark:text-ink-100">
            <Ban size={16} className="text-ink-400 dark:text-ink-500" />
            Active suppressions
            {list.data?.length ? (
              <span className="ml-2 inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-ink-100 px-1.5 font-display text-[11px] font-bold text-ink-700 dark:bg-white/10 dark:text-ink-200">
                {list.data.length}
              </span>
            ) : null}
          </div>
          {list.isPending ? (
            <p className="p-6 text-sm text-ink-500 dark:text-ink-400">Loading…</p>
          ) : !list.data?.length ? (
            <EmptyState
              icon={ShieldOff}
              title="No rules suppressed"
              description="All validation findings will appear in your reports. Suppress noisy rules from the panel on the left."
            />
          ) : (
            <ul className="divide-y divide-ink-100 dark:divide-white/[0.05]">
              {list.data.map((p) => (
                <li
                  key={p.rule_id}
                  className="flex items-center justify-between px-5 py-3 text-sm transition-colors hover:bg-ink-50/60 dark:hover:bg-white/[0.04]"
                >
                  <code className="font-mono text-sm font-semibold text-ink-800 dark:text-white">
                    {p.rule_id}
                  </code>
                  <button
                    type="button"
                    onClick={() => del.mutate(p.rule_id)}
                    disabled={del.isPending}
                    className="rounded-md p-1.5 text-danger-600 transition-colors hover:bg-danger-50 hover:text-danger-700 dark:text-danger-400 dark:hover:bg-danger-500/10 dark:hover:text-danger-300"
                    title="Remove suppression"
                  >
                    <Trash2 size={15} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
