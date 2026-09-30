"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, PackageCheck } from "lucide-react";

import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import { apiJson } from "@/lib/api";
import { OUTCOME_LABEL, type Outcome } from "@/lib/validation";
import { cn } from "@/lib/utils";

type PackCheck = {
  rule_id: string; name: string; material: boolean; enabled: boolean; runs_in_validation: boolean;
  requires: string[]; last_run: Record<Outcome, number> | null;
};
type Pack = {
  key: string; name: string; purpose: string; elsewhere: string | null;
  checks: PackCheck[];
  required_inputs: { input: string; checks: string[] }[];
  state: "on" | "off" | "partial" | "not_applicable";
  last_run: { period_month: string; run_number: number; totals: Record<Outcome, number>; coverage_pct: number | null } | null;
};

const STATE_LABEL: Record<Pack["state"], string> = {
  on: "On", off: "Off", partial: "Partly on", not_applicable: "Outside validation",
};

/**
 * The built-in checks grouped by what they protect. Each pack says what it
 * needs to run and how its checks fared in the latest run, so "no failures"
 * can be read against "how much of this was actually checked".
 */
export function RulePacks({ entityId, canChange }: { entityId: string | undefined; canChange: boolean }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState<string | null>(null);
  const [pending, setPending] = useState<{ key: string; enabled: boolean } | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const packs = useQuery({
    queryKey: ["rule-packs", entityId],
    queryFn: () => apiJson<Pack[]>("/api/validation-matrix/packs"),
    enabled: !!entityId,
  });
  const toggle = useMutation({
    mutationFn: (body: { key: string; enabled: boolean; reason: string }) =>
      apiJson(`/api/validation-matrix/packs/${body.key}`, {
        method: "PUT", body: JSON.stringify({ enabled: body.enabled, reason: body.reason }),
      }),
    onSuccess: () => {
      setError(null); setPending(null); setReason("");
      void qc.invalidateQueries({ queryKey: ["rule-packs", entityId] });
      void qc.invalidateQueries({ queryKey: ["matrix-preferences", entityId] });
    },
    onError: (e: Error) => setError(e.message),
  });

  return (
    <Card><CardContent className="space-y-3 py-5">
      <div>
        <h2 className="flex items-center gap-2 text-base font-semibold text-ink-900"><PackageCheck size={17} /> Rule packs</h2>
        <p className="text-xs text-ink-500">
          Built-in checks grouped by what they protect. A pack switched off reports its checks as <strong>Disabled</strong> in every run — never as passed. Coverage is from the latest current run.
        </p>
      </div>
      {error ? <AlertBanner variant="error" title="Not changed">{error}</AlertBanner> : null}
      {packs.isError ? <AlertBanner variant="error" title="Could not load rule packs">Retry this page.</AlertBanner> : null}
      <div className="divide-y divide-ink-200">
        {(packs.data ?? []).map((pack) => {
          const expanded = open === pack.key;
          return (
            <div key={pack.key} className="py-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <button type="button" className="flex min-w-0 flex-1 items-start gap-2 text-left" aria-expanded={expanded}
                  onClick={() => setOpen(expanded ? null : pack.key)}>
                  {expanded ? <ChevronDown size={16} className="mt-0.5 shrink-0" /> : <ChevronRight size={16} className="mt-0.5 shrink-0" />}
                  <span>
                    <span className="block text-sm font-semibold text-ink-900">{pack.name}
                      <span className="ml-2 text-xs font-normal text-ink-500">{pack.checks.length} check(s) · {STATE_LABEL[pack.state]}</span>
                    </span>
                    <span className="block text-xs text-ink-500">{pack.elsewhere ?? pack.purpose}</span>
                  </span>
                </button>
                <div className="flex items-center gap-3 text-xs">
                  {pack.last_run ? (
                    <span className={cn("font-semibold", (pack.last_run.totals.cannot_validate ?? 0) > 0 ? "text-warning-700" : "text-ink-600")}>
                      {pack.last_run.coverage_pct != null ? `${pack.last_run.coverage_pct}% checked` : "not applicable"} ·{" "}
                      {pack.last_run.totals.failed} failed · {pack.last_run.totals.cannot_validate} could not run
                    </span>
                  ) : pack.checks.length ? <span className="text-ink-500">no run yet</span> : null}
                  {canChange && pack.checks.length ? (
                    <button type="button" className="rounded-lg border border-ink-200 px-2.5 py-1 font-semibold text-ink-700 hover:bg-ink-50"
                      onClick={() => { setPending({ key: pack.key, enabled: pack.state !== "on" }); setReason(""); }}>
                      {pack.state === "on" ? "Switch off…" : "Switch on…"}
                    </button>
                  ) : null}
                </div>
              </div>
              {pending?.key === pack.key ? (
                <div className="mt-2 flex flex-wrap items-end gap-2 rounded-lg bg-ink-50 p-2">
                  <label className="min-w-64 flex-1 text-xs font-semibold text-ink-700">
                    Why {pending.enabled ? "switch it on" : "switch it off"}? (kept in the audit trail)
                    <input className="mt-1 w-full rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm" value={reason}
                      onChange={(e) => setReason(e.target.value)} />
                  </label>
                  <button type="button" disabled={reason.trim().length < 8 || toggle.isPending}
                    className="rounded-lg bg-brand-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
                    onClick={() => toggle.mutate({ key: pack.key, enabled: pending.enabled, reason: reason.trim() })}>
                    Confirm
                  </button>
                  <button type="button" className="px-2 py-2 text-xs text-ink-600" onClick={() => setPending(null)}>Cancel</button>
                </div>
              ) : null}
              {expanded ? (
                <div className="mt-3 space-y-3 pl-6">
                  {pack.required_inputs.length ? (
                    <div>
                      <p className="text-xs font-semibold text-ink-700">What these checks need</p>
                      <ul className="mt-1 space-y-0.5 text-xs text-ink-600">
                        {pack.required_inputs.map((r) => (
                          <li key={r.input}><strong>{r.input}</strong> — used by {r.checks.join(", ")}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  <ul className="space-y-1 text-xs">
                    {pack.checks.map((c) => (
                      <li key={c.rule_id} className="flex flex-wrap items-center gap-x-2">
                        <span className="w-24 shrink-0 font-mono text-ink-500">{c.rule_id}</span>
                        <span className="text-ink-800">{c.name}</span>
                        {c.material ? <span className="rounded bg-ink-100 px-1 text-[11px] font-semibold text-ink-600">statutory</span> : null}
                        {!c.enabled ? <span className="rounded bg-ink-200 px-1 text-[11px] font-semibold text-ink-600">disabled</span> : null}
                        {!c.runs_in_validation ? <span className="text-ink-500">checked at upload</span> : null}
                        {c.last_run ? (
                          <span className="text-ink-500">
                            {(["passed", "failed", "cannot_validate", "not_applicable"] as Outcome[])
                              .filter((o) => c.last_run![o]).map((o) => `${OUTCOME_LABEL[o]} ${c.last_run![o]}`).join(" · ")}
                          </span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </CardContent></Card>
  );
}
