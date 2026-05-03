"use client";

import { apiFetch, parseEnvelopeResponse } from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { toast } from "sonner";
import {
  UploadCloud,
  FileSpreadsheet,
  Play,
  CheckCircle2,
  X,
  ChevronRight,
  HelpCircle,
  ShieldCheck,
  History,
  Info,
  Loader2,
} from "lucide-react";

type PreviewRow = Record<string, unknown>;

const STEP_LABELS = ["Upload file", "Configure run", "Validate"];

export default function UploadPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [strict, setStrict] = useState(true);
  const [runType, setRunType] = useState<"regular" | "arrear" | "increment_arrear">("regular");
  const [periodMonth, setPeriodMonth] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [preview, setPreview] = useState<PreviewRow[]>([]);
  const [columns, setColumns] = useState<string[]>([]);
  const [employees, setEmployees] = useState<PreviewRow[]>([]);
  const [missing, setMissing] = useState<string[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<0 | 1 | 2>(0);

  const onFile = (f: File | null) => {
    setFile(f);
    setPreview([]);
    setEmployees([]);
    setColumns([]);
    setMissing([]);
    setWarnings([]);
    setError(null);
    if (f) {
      setStep(1);
      toast.info("File ready", { description: f.name });
    }
  };

  const parseUpload = useCallback(async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    const fd = new FormData();
    fd.append("file", file);
    fd.append(
      "meta",
      JSON.stringify({
        run_type: runType,
        period_month: periodMonth || null,
        effective_month_from: from || null,
        effective_month_to: to || null,
        strict_header_check: strict,
      }),
    );
    const res = await apiFetch("/api/payroll/upload", { method: "POST", body: fd });
    let data: {
      columns: string[];
      preview: PreviewRow[];
      employees: PreviewRow[];
      missing_required?: string[];
      warnings?: string[];
    };
    try {
      data = await parseEnvelopeResponse(res);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Upload failed — check your file format.";
      setError(msg);
      toast.error("Parse failed", { description: msg });
      setBusy(false);
      return;
    }
    setColumns(data.columns);
    setPreview(data.preview);
    setEmployees(data.employees);
    setMissing(data.missing_required || []);
    setWarnings(data.warnings || []);
    setBusy(false);
    setStep(2);
    toast.success("Register parsed", {
      description: `${data.employees.length.toLocaleString("en-IN")} employees · ${data.columns.length} columns`,
    });
  }, [file, runType, periodMonth, from, to, strict]);

  const runValidate = async () => {
    if (!employees.length) {
      setError("Parse a file first.");
      toast.error("Nothing to validate", { description: "Parse the register before running validation." });
      return;
    }
    setBusy(true);
    setError(null);
    const res = await apiFetch("/api/payroll/validate", {
      method: "POST",
      body: JSON.stringify({
        employees,
        run_type: runType,
        period_month: periodMonth || null,
        effective_month_from: from || null,
        effective_month_to: to || null,
      }),
    });
    try {
      const data = await parseEnvelopeResponse(res) as {
        results: unknown[];
        findings?: unknown[];
        findings_summary?: unknown;
        risk_scores?: unknown[];
      };
      sessionStorage.setItem("payroll_results", JSON.stringify(data.results));
      sessionStorage.setItem("payroll_findings", JSON.stringify(data.findings || []));
      sessionStorage.setItem("payroll_findings_summary", JSON.stringify(data.findings_summary || {}));
      sessionStorage.setItem("payroll_risk_scores", JSON.stringify(data.risk_scores || []));
      sessionStorage.setItem(
        "payroll_validate_request",
        JSON.stringify({
          employees,
          run_type: runType,
          period_month: periodMonth || null,
          effective_month_from: from || null,
          effective_month_to: to || null,
        }),
      );
      sessionStorage.setItem(
        "payroll_meta",
        JSON.stringify({
          run_type: runType,
          period_month: periodMonth,
          from,
          to,
          columns,
          filename: file?.name,
        }),
      );
      toast.success("Validation complete", {
        description: "Opening detailed results.",
      });
      router.push("/payroll/results");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Validation failed.";
      setError(msg);
      toast.error("Validation failed", { description: msg });
    } finally {
      setBusy(false);
    }
  };

  const needsArrearDates = runType === "arrear" || runType === "increment_arrear";

  return (
    <div className="mx-auto max-w-3xl space-y-7">
      <PageHeader
        eyebrow="Validation engine"
        title="Upload & validate payroll"
        description="Import a salary register (CSV / Excel), set run parameters, preview rows, then run a full statutory validation pass."
        actions={
          <Button variant="outline" asChild>
            <Link href="/payroll/history" className="gap-2">
              <History size={15} strokeWidth={2} /> History
            </Link>
          </Button>
        }
      />

      {/* Step indicator — segmented progress */}
      <div className="flex items-center gap-3 rounded-2xl border border-ink-200/70 bg-white p-3 shadow-soft">
        {STEP_LABELS.map((label, i) => {
          const done = i < step;
          const current = i === step;
          return (
            <div key={label} className="flex flex-1 items-center gap-2.5">
              <div
                className={`flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl border-2 text-xs font-bold transition-all ${
                  done
                    ? "border-success-500 bg-gradient-to-br from-success-50 to-white text-success-700 shadow-sm"
                    : current
                      ? "border-brand-500 bg-gradient-to-br from-brand-50 to-accent-50 text-brand-700 shadow-sm"
                      : "border-ink-200 bg-white text-ink-400"
                }`}
              >
                {done ? <CheckCircle2 size={16} strokeWidth={2.5} /> : i + 1}
              </div>
              <span
                className={`hidden text-[12px] font-semibold sm:inline ${
                  done ? "text-success-700" : current ? "text-ink-900" : "text-ink-400"
                }`}
              >
                {label}
              </span>
              {i < STEP_LABELS.length - 1 && (
                <div
                  className={`mx-2 hidden h-0.5 min-w-[1rem] flex-1 rounded-full transition-colors sm:block ${
                    done ? "bg-success-300" : "bg-ink-100"
                  }`}
                />
              )}
            </div>
          );
        })}
      </div>

      {/* Step 0: Premium dropzone */}
      <div
        className={`group relative overflow-hidden rounded-2xl border-2 border-dashed transition-all ${
          drag
            ? "border-brand-500 bg-gradient-to-br from-brand-50 to-accent-50 ring-4 ring-brand-500/15"
            : file
              ? "border-success-300 bg-gradient-to-br from-success-50/60 to-white"
              : "border-ink-200 bg-white hover:border-brand-300"
        }`}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          const f = e.dataTransfer.files?.[0];
          if (f) onFile(f);
        }}
      >
        <div
          aria-hidden
          className={`pointer-events-none absolute -right-20 -top-20 h-56 w-56 rounded-full blur-3xl transition-opacity ${
            drag || file
              ? "bg-gradient-to-br from-brand-300/40 to-accent-300/40 opacity-100"
              : "bg-brand-200/30 opacity-0 group-hover:opacity-100"
          }`}
        />
        <div className="relative px-6 py-14 text-center sm:py-16">
          {file ? (
            <div className="mx-auto flex max-w-md flex-col items-center gap-4">
              <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-white shadow-soft ring-1 ring-success-300/40">
                <FileSpreadsheet className="h-8 w-8 text-success-600" strokeWidth={1.75} />
              </div>
              <div>
                <p className="font-display text-lg font-bold text-ink-900">{file.name}</p>
                <p className="mt-1 text-sm text-ink-500">
                  {(file.size / 1024).toFixed(1)} KB · ready to configure
                </p>
              </div>
              <button
                type="button"
                onClick={() => onFile(null)}
                className="inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs font-semibold text-ink-500 transition-colors hover:bg-white hover:text-danger-600"
              >
                <X size={13} /> Remove file
              </button>
            </div>
          ) : (
            <div className="mx-auto flex max-w-lg flex-col items-center gap-5">
              <div className="relative">
                <div className="absolute inset-0 -m-2 animate-pulse-soft rounded-2xl bg-gradient-to-br from-brand-300/30 to-accent-300/30 blur-xl" />
                <div className="relative flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-600 to-accent-600 shadow-glow">
                  <UploadCloud className="h-8 w-8 text-white" strokeWidth={2} />
                </div>
              </div>
              <div>
                <p className="font-display text-lg font-bold tracking-tight text-ink-900">
                  Drop your register, or browse
                </p>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-500">
                  Payroll CSV / Excel (<code className="rounded bg-ink-100 px-1 text-[11px]">.csv</code>,{" "}
                  <code className="rounded bg-ink-100 px-1 text-[11px]">.xlsx</code>,{" "}
                  <code className="rounded bg-ink-100 px-1 text-[11px]">.xls</code>).
                </p>
              </div>
              <label className="group/btn inline-flex cursor-pointer items-center gap-2 rounded-xl bg-gradient-to-br from-brand-600 to-accent-600 px-6 py-3 text-sm font-semibold text-white shadow-soft transition-all hover:shadow-glow">
                <UploadCloud size={16} strokeWidth={2.25} />
                Choose file
                <input
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  className="hidden"
                  onChange={(e) => onFile(e.target.files?.[0] || null)}
                />
              </label>
              <p className="text-[11px] text-ink-400">
                Rows align with salary components configured for your tenant.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Step 1: Run options */}
      {step >= 1 ? (
        <Card className="overflow-hidden shadow-soft ring-1 ring-slate-900/[0.04]">
          <CardContent className="border-b border-slate-100 px-6 py-4">
            <h2 className="text-base font-semibold text-slate-900">Run configuration</h2>
            <p className="mt-1 text-sm text-slate-600">
              Payroll period and engine mode. These values are persisted with validation results.
            </p>
          </CardContent>
          <CardContent className="space-y-6 px-6 py-6">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Run type</p>
              <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
                {(
                  [
                    { id: "regular", label: "Regular", desc: "Standard monthly run" },
                    { id: "arrear", label: "Arrear", desc: "Past-period correction" },
                    { id: "increment_arrear", label: "Increment + arrear", desc: "With CTC delta" },
                  ] as const
                ).map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => setRunType(t.id)}
                    className={`group relative overflow-hidden rounded-xl border px-4 py-3 text-left text-sm font-semibold transition-all ${
                      runType === t.id
                        ? "border-brand-500 bg-gradient-to-br from-brand-50 to-accent-50 text-brand-900 shadow-sm ring-1 ring-brand-500/20"
                        : "border-ink-200 bg-white text-ink-700 hover:border-brand-300 hover:bg-ink-50"
                    }`}
                  >
                    {runType === t.id && (
                      <span
                        aria-hidden
                        className="absolute right-2 top-2 h-2 w-2 rounded-full bg-gradient-to-br from-brand-500 to-accent-500"
                      />
                    )}
                    <p className="font-display">{t.label}</p>
                    <p className="mt-0.5 text-[11px] font-medium text-ink-500">{t.desc}</p>
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Period month
              </label>
              <p className="mb-2 mt-0.5 text-xs text-slate-500">
                Typically the first day of the payroll month (<code className="font-mono">YYYY-MM-DD</code>).
              </p>
              <input
                type="date"
                className="h-11 w-full max-w-xs rounded-xl border border-slate-200 bg-white px-3 text-sm font-medium shadow-sm outline-none ring-brand-500/20 transition-shadow focus-visible:ring-[3px]"
                value={periodMonth}
                onChange={(e) => setPeriodMonth(e.target.value)}
              />
              <p className="mt-2 flex items-start gap-1.5 text-xs leading-relaxed text-slate-500">
                <Info size={13} className="mt-0.5 shrink-0 text-slate-400" />
                Used to persist the salary register snapshot and MoM comparisons.
              </p>
            </div>

            {needsArrearDates ? (
              <div className="grid gap-5 sm:grid-cols-2">
                <div>
                  <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Effective from</label>
                  <input
                    type="date"
                    className="mt-2 h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm shadow-sm outline-none ring-brand-500/20 focus-visible:ring-[3px]"
                    value={from}
                    onChange={(e) => setFrom(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Effective to</label>
                  <input
                    type="date"
                    className="mt-2 h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm shadow-sm outline-none ring-brand-500/20 focus-visible:ring-[3px]"
                    value={to}
                    onChange={(e) => setTo(e.target.value)}
                  />
                </div>
              </div>
            ) : null}

            <label className="flex cursor-pointer items-start gap-4 rounded-xl border border-slate-100 bg-slate-50/60 p-4 transition-colors hover:bg-slate-50">
              <div className="relative mt-0.5 shrink-0">
                <input
                  type="checkbox"
                  checked={strict}
                  onChange={(e) => setStrict(e.target.checked)}
                  className="sr-only"
                />
                <div
                  className={`flex h-5 w-5 items-center justify-center rounded-md border-2 transition-colors ${strict ? "border-brand-600 bg-brand-600" : "border-slate-300 bg-white"}`}
                >
                  {strict ? <CheckCircle2 size={12} className="text-white" strokeWidth={3} /> : null}
                </div>
              </div>
              <div>
                <p className="font-semibold text-slate-900">Strict header check</p>
                <p className="mt-1 text-sm leading-relaxed text-slate-600">
                  Require every mapped salary-component column to exist in the file (recommended for audits).
                </p>
              </div>
            </label>

            <Button
              type="button"
              disabled={!file || busy}
              onClick={() => void parseUpload()}
              className="h-11 rounded-xl px-6 font-semibold shadow-soft"
              variant={file && !busy ? "default" : "secondary"}
            >
              {busy ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Parsing…
                </>
              ) : (
                <>
                  <Play size={16} strokeWidth={2} /> Parse & preview
                </>
              )}
            </Button>
          </CardContent>
        </Card>
      ) : null}

      {busy && step >= 2 && preview.length === 0 ? (
        <AlertBanner variant="info" title="Hang tight">
          Parsing your file… large registers can take a few seconds.
          <span className="mt-3 block flex gap-2">
            <Skeleton className="h-2 flex-1 rounded-full" />
            <Skeleton className="h-2 w-24 rounded-full" />
          </span>
        </AlertBanner>
      ) : null}

      {error ? (
        <AlertBanner variant="error" title="We could not finish that step">
          {error}
        </AlertBanner>
      ) : null}

      {missing.length > 0 ? (
        <AlertBanner variant="warning" title="Missing required columns">
          <div className="mt-2 flex flex-wrap gap-1.5">
            {missing.map((m) => (
              <span
                key={m}
                className="inline-flex rounded-lg bg-white/70 px-2 py-1 font-mono text-xs font-semibold text-amber-950 shadow-sm ring-1 ring-amber-200/60"
              >
                {m}
              </span>
            ))}
          </div>
        </AlertBanner>
      ) : null}

      {warnings.length > 0 ? (
        <AlertBanner variant="info" title="Parser notices">
          <ul className="mt-2 space-y-1.5">
            {warnings.map((w) => (
              <li key={w} className="flex items-start gap-1.5 text-xs">
                <ChevronRight size={12} className="mt-0.5 shrink-0 opacity-70" aria-hidden /> {w}
              </li>
            ))}
          </ul>
        </AlertBanner>
      ) : null}

      {/* Step 2: Preview + Validate */}
      {step >= 2 && employees.length > 0 ? (
        <Card className="overflow-hidden shadow-soft ring-1 ring-slate-900/[0.04]">
          <div className="flex flex-col gap-4 border-b border-slate-100 px-6 py-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-50 ring-1 ring-emerald-200/60">
                <CheckCircle2 className="h-5 w-5 text-emerald-700" strokeWidth={2} />
              </div>
              <div>
                <p className="font-semibold text-slate-900">
                  {employees.length.toLocaleString("en-IN")} employees parsed
                </p>
                <p className="text-sm text-slate-600">{columns.length} columns mapped</p>
              </div>
            </div>
            <Button
              type="button"
              disabled={busy}
              onClick={() => void runValidate()}
              className="w-full shrink-0 rounded-xl px-6 font-semibold shadow-soft sm:w-auto"
            >
              {busy ? (
                <>
                  <Loader2 size={17} strokeWidth={2} className="animate-spin" /> Validating…
                </>
              ) : (
                <>
                  <ShieldCheck size={17} strokeWidth={2} /> Run validation
                </>
              )}
            </Button>
          </div>

          <div className="border-b border-slate-100 bg-slate-50/70 px-6 py-4">
            <p className="text-2xs font-semibold uppercase tracking-widest text-slate-500">Columns detected</p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {columns.map((c) => (
                <span
                  key={c}
                  className="rounded-lg bg-white px-2 py-1 font-mono text-2xs font-medium text-slate-700 shadow-sm ring-1 ring-slate-200/80"
                >
                  {c}
                </span>
              ))}
            </div>
          </div>

          {preview.length > 0 ? (
            <div className="overflow-x-auto">
              <p className="border-b border-slate-100 px-6 py-2.5 text-2xs font-semibold uppercase tracking-wide text-slate-500">
                Preview · first {preview.length} rows
              </p>
              <table className="min-w-full text-xs">
                <thead className="sticky top-0 border-b border-slate-100 bg-slate-50/95 text-left text-2xs font-semibold uppercase tracking-wide text-slate-500 backdrop-blur">
                  <tr>
                    {Object.keys(preview[0]).map((k) => (
                      <th key={k} className="whitespace-nowrap px-5 py-2.5 font-semibold">
                        {k}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {preview.map((row, idx) => (
                    <tr key={idx} className="hover:bg-slate-50/70">
                      {Object.values(row).map((v, i) => (
                        <td key={i} className="whitespace-nowrap px-5 py-2 text-slate-700">
                          {String(v ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </Card>
      ) : null}

      {step >= 2 && file && busy && preview.length === 0 ? (
        <Card>
          <CardContent className="space-y-4 p-6">
            <div className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin text-brand-600" />{" "}
              <Skeleton className="h-5 w-48" />
            </div>
            <Skeleton className="h-28 w-full rounded-xl" />
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
