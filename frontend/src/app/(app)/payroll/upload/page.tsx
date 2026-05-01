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
    <div className="mx-auto max-w-3xl space-y-8">
      <PageHeader
        title="Upload & validate payroll"
        description="Import a salary register (CSV / Excel), set the payroll run parameters, preview rows, then run statutory validation."
        actions={
          <Button variant="outline" asChild className="rounded-xl border-slate-200 bg-white shadow-sm">
            <Link href="/payroll/history" className="gap-2">
              <History size={15} strokeWidth={2} /> History
            </Link>
          </Button>
        }
      />

      {/* Step indicator */}
      <Card className="overflow-hidden shadow-soft">
        <CardContent className="flex flex-wrap items-center gap-2 p-4 sm:gap-0 sm:p-5">
          {STEP_LABELS.map((label, i) => (
            <div key={label} className="flex flex-1 items-center sm:min-w-0">
              <div
                className={`flex items-center gap-2.5 ${
                  i < step ? "text-emerald-600" : i === step ? "text-brand-700" : "text-slate-400"
                }`}
              >
                <div
                  className={`flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full border-2 text-xs font-bold transition-colors ${
                    i < step
                      ? "border-emerald-500 bg-emerald-50 shadow-sm"
                      : i === step
                        ? "border-brand-600 bg-brand-50 shadow-sm"
                        : "border-slate-200 bg-white"
                  }`}
                >
                  {i < step ? <CheckCircle2 size={16} strokeWidth={2.25} aria-hidden /> : i + 1}
                </div>
                <span className="hidden text-xs font-semibold sm:inline">{label}</span>
              </div>
              {i < STEP_LABELS.length - 1 && (
                <div className={`mx-3 hidden h-0.5 min-w-[1rem] flex-1 sm:block ${i < step ? "bg-emerald-200" : "bg-slate-200"}`} />
              )}
            </div>
          ))}
        </CardContent>
      </Card>

      {/* Step 0: File upload */}
      <Card className={`overflow-hidden transition-shadow ${drag ? "ring-2 ring-brand-400/50" : ""}`}>
        <CardContent className="p-0">
          <div
            className={`px-6 py-12 text-center transition-colors sm:py-14 ${
              drag ? "bg-brand-50/90" : file ? "bg-emerald-50/40" : "bg-slate-50/60"
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
            {file ? (
              <div className="mx-auto flex max-w-md flex-col items-center gap-3">
                <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-white shadow-soft ring-1 ring-emerald-200/80">
                  <FileSpreadsheet className="h-7 w-7 text-emerald-700" strokeWidth={1.75} />
                </div>
                <div>
                  <p className="font-semibold text-slate-900">{file.name}</p>
                  <p className="mt-1 text-sm text-slate-500">
                    {(file.size / 1024).toFixed(1)} KB · ready to configure
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => onFile(null)}
                  className="mt-2 inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-slate-500 transition-colors hover:bg-white/80 hover:text-red-600"
                >
                  <X size={13} aria-hidden /> Remove file
                </button>
              </div>
            ) : (
              <div className="mx-auto flex max-w-lg flex-col items-center gap-4">
                <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-white shadow-soft ring-1 ring-slate-900/[0.06]">
                  <UploadCloud className="h-7 w-7 text-brand-600" strokeWidth={1.75} />
                </div>
                <div>
                  <p className="text-base font-semibold text-slate-900">Drop your register here</p>
                  <p className="mt-1 text-sm text-slate-600">
                    Payroll CSV / Excel (.csv, .xlsx, .xls). Drag in or browse.
                  </p>
                </div>
                <label className="inline-flex cursor-pointer items-center rounded-xl bg-brand-600 px-6 py-2.5 text-sm font-semibold text-white shadow-soft transition hover:bg-brand-700">
                  Choose file
                  <input
                    type="file"
                    accept=".csv,.xlsx,.xls"
                    className="hidden"
                    onChange={(e) => onFile(e.target.files?.[0] || null)}
                  />
                </label>
              </div>
            )}
          </div>
          <div className="border-t border-slate-100 px-6 py-3 text-center text-xs text-slate-500">
            Rows should align with salary components configured for your tenant.
          </div>
        </CardContent>
      </Card>

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
                {(["regular", "arrear", "increment_arrear"] as const).map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setRunType(t)}
                    className={`rounded-xl border px-4 py-3 text-left text-sm font-semibold transition-all ${
                      runType === t
                        ? "border-brand-500 bg-brand-50 text-brand-900 shadow-sm ring-1 ring-brand-500/15"
                        : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                    }`}
                  >
                    {t === "regular" ? "Regular" : t === "arrear" ? "Arrear" : "Increment + arrear"}
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
