"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Download, Loader2, UploadCloud } from "lucide-react";

import { Menu, MenuItem } from "@/components/cost/Menu";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import { apiAbsoluteUrl, apiFetch, parseEnvelopeResponse } from "@/lib/api";
import { fetchDimensions, formatINR } from "@/lib/cost-analysis";

type PreviewLine = {
  period: string;
  scope_value: string;
  amount: number;
  headcount: number | null;
};

type Preview = {
  filename: string;
  scope_key: string;
  line_count: number;
  total: number;
  periods: string[];
  scopes: string[];
  problems: string[];
  lines: PreviewLine[];
  truncated: boolean;
};

const MEASURES = [
  { key: "ctc", label: "Total CTC", hint: "Gross plus employer contributions" },
  { key: "gross", label: "Gross pay", hint: "What the register pays out" },
  { key: "employer_cost", label: "Employer contributions", hint: "EPF, ESI, gratuity, LWF" },
];

/**
 * Budget upload, in two steps.
 *
 * A budget is a decision, and a decision taken by dragging a file onto a page
 * without seeing what it said is not one. The preview is where a finance team
 * finds the duplicate department line and the month that read as 2025.
 */
export default function BudgetUploadPage() {
  const queryClient = useQueryClient();
  const dims = useQuery({ queryKey: ["bi", "dimensions"], queryFn: fetchDimensions });

  const [file, setFile] = useState<File | null>(null);
  const [scopeKey, setScopeKey] = useState("entity");
  const [measure, setMeasure] = useState("ctc");
  const [name, setName] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const scopes = [
    { key: "entity", label: "Whole entity" },
    ...(dims.data?.dimensions ?? []).map((d) => ({ key: d.key, label: d.label })),
  ];
  const scopeLabel = scopes.find((s) => s.key === scopeKey)?.label ?? "Whole entity";

  async function runPreview(next: File, scope: string) {
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      const form = new FormData();
      form.append("file", next);
      form.append("scope_key", scope);
      const res = await apiFetch("/api/budget/preview", { method: "POST", body: form });
      setPreview(await parseEnvelopeResponse<Preview>(res));
    } catch (e) {
      setError((e as Error).message);
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }

  async function commit() {
    if (!file || !name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("name", name.trim());
      form.append("scope_key", scopeKey);
      form.append("measure", measure);
      const res = await apiFetch("/api/budget/versions", { method: "POST", body: form });
      const data = await parseEnvelopeResponse<{ name: string }>(res);
      setSaved(data.name ?? name.trim());
      setPreview(null);
      setFile(null);
      setName("");
      queryClient.invalidateQueries({ queryKey: ["budget"] });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Budget"
        title="Upload an approved budget"
        description="Two steps on purpose: read the file, check what it says, then store it. A budget lands as a draft and is not used as the comparison on any dashboard until someone with authority approves it."
      />

      {saved && (
        <AlertBanner variant="success" title={`Stored “${saved}” as a draft`}>
          It is not the comparison yet. Approve it under Cost analysis → Budget &amp; forecast,
          which is an owner or manager action.
        </AlertBanner>
      )}
      {error && <AlertBanner variant="error" title="Could not read that file">{error}</AlertBanner>}

      <Card>
        <CardContent className="space-y-4 py-5">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Menu label="Budget is set at" summary={scopeLabel} width="w-64">
              {(close) =>
                scopes.map((scope) => (
                  <MenuItem
                    key={scope.key}
                    selected={scope.key === scopeKey}
                    onClick={() => {
                      setScopeKey(scope.key);
                      close();
                      if (file) runPreview(file, scope.key);
                    }}
                  >
                    {scope.label}
                  </MenuItem>
                ))
              }
            </Menu>

            <Menu
              label="Budget is set on"
              summary={MEASURES.find((m) => m.key === measure)?.label ?? "Total CTC"}
              width="w-72"
            >
              {(close) =>
                MEASURES.map((option) => (
                  <MenuItem
                    key={option.key}
                    selected={option.key === measure}
                    hint={option.hint}
                    onClick={() => { setMeasure(option.key); close(); }}
                  >
                    {option.label}
                  </MenuItem>
                ))
              }
            </Menu>

            <label className="flex flex-col gap-1.5">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                Name this version
              </span>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="FY27 approved plan"
                className="h-9 rounded-lg border border-ink-200 bg-white px-3 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-brand-500 dark:border-white/10 dark:bg-white/[0.04] dark:text-white"
              />
            </label>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-ink-200 bg-white px-3.5 py-2 text-sm font-medium text-ink-700 hover:bg-ink-50 dark:border-white/10 dark:bg-white/[0.04] dark:text-ink-200 dark:hover:bg-white/[0.07]">
              <UploadCloud size={15} />
              {file ? file.name : "Choose a .csv or .xlsx"}
              <input
                type="file"
                accept=".csv,.xlsx"
                className="hidden"
                onChange={(e) => {
                  const next = e.target.files?.[0] ?? null;
                  setFile(next);
                  if (next) runPreview(next, scopeKey);
                }}
              />
            </label>
            <a
              href={apiAbsoluteUrl("/api/budget/template.csv")}
              className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-700 underline dark:text-brand-300"
            >
              <Download size={14} /> Template
            </a>
            {busy && <Loader2 size={16} className="animate-spin text-ink-400" />}
          </div>

          <p className="text-xs text-ink-500 dark:text-ink-400">
            The file needs a month, a scope and an amount. Months are read as{" "}
            <code>2026-04</code>, <code>Apr 2026</code> or <code>04/2026</code>; anything else is
            reported rather than guessed at. Columns the product does not recognise are kept
            against the line rather than dropped.
          </p>
        </CardContent>
      </Card>

      {preview && (
        <Card>
          <CardContent className="space-y-4 py-5">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <h3 className="text-base font-semibold text-ink-900 dark:text-white">
                {preview.line_count} line{preview.line_count === 1 ? "" : "s"} read from{" "}
                {preview.filename}
              </h3>
              <span className="font-display text-lg font-semibold tabular-nums text-ink-900 dark:text-white">
                {formatINR(preview.total, true)}
              </span>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <Fact label="Months" value={`${preview.periods.length}`} />
              <Fact label="Scopes" value={`${preview.scopes.length}`} />
              <Fact
                label="Problems"
                value={`${preview.problems.length}`}
                tone={preview.problems.length ? "warn" : "ok"}
              />
            </div>

            {preview.problems.length > 0 && (
              <div className="rounded-lg border border-warning-200 bg-warning-50 p-3 dark:border-warning-500/30 dark:bg-warning-500/10">
                <p className="flex items-center gap-1.5 pb-1.5 text-xs font-semibold text-warning-800 dark:text-warning-300">
                  <AlertTriangle size={13} /> These rows were not read
                </p>
                <ul className="space-y-0.5 text-xs text-warning-800 dark:text-warning-300">
                  {preview.problems.slice(0, 12).map((problem) => (
                    <li key={problem}>· {problem}</li>
                  ))}
                  {preview.problems.length > 12 && (
                    <li>· and {preview.problems.length - 12} more</li>
                  )}
                </ul>
              </div>
            )}

            <div className="max-h-72 overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-white dark:bg-ink-900">
                  <tr className="border-b border-ink-200 text-[10px] uppercase tracking-wide text-ink-400 dark:border-white/10">
                    <th className="py-2 text-left font-semibold">Month</th>
                    <th className="py-2 text-left font-semibold">Scope</th>
                    <th className="py-2 text-right font-semibold">Amount</th>
                    <th className="py-2 text-right font-semibold">Headcount</th>
                  </tr>
                </thead>
                <tbody className="tabular-nums">
                  {preview.lines.map((line) => (
                    <tr key={`${line.period}:${line.scope_value}`}
                        className="border-b border-ink-100 last:border-0 dark:border-white/5">
                      <td className="py-1.5 pr-3 text-ink-800 dark:text-ink-100">
                        {new Date(line.period).toLocaleDateString("en-IN",
                          { month: "short", year: "numeric" })}
                      </td>
                      <td className="py-1.5 pr-3 text-ink-600 dark:text-ink-300">
                        {line.scope_value === "entity" ? "Whole entity" : line.scope_value}
                      </td>
                      <td className="py-1.5 text-right text-ink-900 dark:text-white">
                        {formatINR(line.amount, true)}
                      </td>
                      <td className="py-1.5 text-right text-ink-500 dark:text-ink-400">
                        {line.headcount ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {preview.truncated && (
                <p className="pt-2 text-xs text-ink-500 dark:text-ink-400">
                  Showing the first 200 lines. All {preview.line_count} will be stored.
                </p>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-3 border-t border-ink-100 pt-3 dark:border-white/5">
              <button
                type="button"
                onClick={commit}
                disabled={busy || !name.trim() || !preview.line_count}
                className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-700 disabled:opacity-50"
              >
                {busy ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                Store as a draft
              </button>
              {!name.trim() && (
                <span className="text-xs text-ink-500 dark:text-ink-400">
                  Give this version a name first — budgets are versioned rather than overwritten.
                </span>
              )}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Fact({ label, value, tone }: { label: string; value: string; tone?: "ok" | "warn" }) {
  return (
    <div className="rounded-xl border border-ink-200/70 px-3 py-2 dark:border-white/10">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">{label}</p>
      <p
        className={
          tone === "warn"
            ? "font-display text-lg font-semibold text-warning-700 dark:text-warning-400"
            : "font-display text-lg font-semibold text-ink-900 dark:text-white"
        }
      >
        {value}
      </p>
    </div>
  );
}
