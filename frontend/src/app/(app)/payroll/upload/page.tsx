"use client";

import { apiFetch } from "@/lib/api";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import {
  UploadCloud,
  FileSpreadsheet,
  Play,
  CheckCircle2,
  AlertTriangle,
  Info,
  X,
  ChevronRight,
  HelpCircle,
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
    if (f) setStep(1);
  };

  const parseUpload = useCallback(async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("meta", JSON.stringify({
      run_type: runType, period_month: periodMonth || null,
      effective_month_from: from || null, effective_month_to: to || null,
      strict_header_check: strict,
    }));
    const res = await apiFetch("/api/payroll/upload", { method: "POST", body: fd });
    if (!res.ok) { setError("Upload failed — check your file format."); setBusy(false); return; }
    const data = await res.json();
    setColumns(data.columns);
    setPreview(data.preview);
    setEmployees(data.employees);
    setMissing(data.missing_required || []);
    setWarnings(data.warnings || []);
    setBusy(false);
    setStep(2);
  }, [file, runType, periodMonth, from, to, strict]);

  const runValidate = async () => {
    if (!employees.length) { setError("Parse a file first."); return; }
    setBusy(true);
    setError(null);
    const res = await apiFetch("/api/payroll/validate", {
      method: "POST",
      body: JSON.stringify({
        employees, run_type: runType,
        period_month: periodMonth || null,
        effective_month_from: from || null,
        effective_month_to: to || null,
      }),
    });
    if (!res.ok) { setError("Validation failed — see backend logs."); setBusy(false); return; }
    const data = await res.json();
    sessionStorage.setItem("payroll_results", JSON.stringify(data.results));
    sessionStorage.setItem("payroll_findings", JSON.stringify(data.findings || []));
    sessionStorage.setItem("payroll_findings_summary", JSON.stringify(data.findings_summary || {}));
    sessionStorage.setItem("payroll_risk_scores", JSON.stringify(data.risk_scores || []));
    sessionStorage.setItem("payroll_meta", JSON.stringify({
      run_type: runType, period_month: periodMonth, from, to, columns, filename: file?.name,
    }));
    setBusy(false);
    router.push("/payroll/results");
  };

  const needsArrearDates = runType === "arrear" || runType === "increment_arrear";

  return (
    <div className="max-w-3xl space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Upload & validate payroll</h1>
        <p className="text-sm text-slate-500 mt-1">
          Upload a CSV or Excel salary register, configure the run, then validate.
        </p>
      </div>

      {/* Step indicator */}
      <div className="flex items-center gap-0">
        {STEP_LABELS.map((label, i) => (
          <div key={label} className="flex items-center flex-1 last:flex-none">
            <div className={`flex items-center gap-2 ${i < step ? "text-success-600" : i === step ? "text-brand-600" : "text-slate-400"}`}>
              <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold border-2 flex-shrink-0 ${
                i < step ? "border-success-500 bg-success-50" :
                i === step ? "border-brand-600 bg-brand-50" :
                "border-slate-200 bg-white"
              }`}>
                {i < step ? <CheckCircle2 size={14} /> : i + 1}
              </div>
              <span className="text-xs font-medium whitespace-nowrap hidden sm:block">{label}</span>
            </div>
            {i < STEP_LABELS.length - 1 && (
              <div className={`flex-1 h-0.5 mx-2 ${i < step ? "bg-success-300" : "bg-slate-200"}`} />
            )}
          </div>
        ))}
      </div>

      {/* Step 0: File upload */}
      <div className={`rounded-xl border-2 transition-all ${
        drag ? "border-brand-400 bg-brand-50" :
        file ? "border-success-300 bg-success-50/50" :
        "border-dashed border-slate-300 bg-white"
      }`}>
        <div
          className="p-8 text-center"
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files?.[0]; if (f) onFile(f); }}
        >
          {file ? (
            <div className="flex flex-col items-center gap-2">
              <div className="w-12 h-12 rounded-xl bg-success-100 flex items-center justify-center">
                <FileSpreadsheet size={22} className="text-success-600" />
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-900">{file.name}</p>
                <p className="text-xs text-slate-500 mt-0.5">
                  {(file.size / 1024).toFixed(1)} KB · Ready to parse
                </p>
              </div>
              <button
                type="button"
                onClick={() => onFile(null)}
                className="flex items-center gap-1 text-xs text-slate-500 hover:text-danger-600 mt-1 transition-colors"
              >
                <X size={12} /> Remove file
              </button>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-3">
              <div className="w-12 h-12 rounded-xl bg-slate-100 flex items-center justify-center">
                <UploadCloud size={22} className="text-slate-400" />
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-700">Drop your file here</p>
                <p className="text-xs text-slate-500 mt-0.5">or click to browse (.csv, .xlsx, .xls)</p>
              </div>
              <label className="cursor-pointer rounded-lg border border-slate-300 bg-white px-4 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 transition-colors shadow-sm">
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
      </div>

      {/* Step 1: Run options */}
      {step >= 1 && (
        <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-100 bg-slate-50/60">
            <h2 className="font-semibold text-slate-900 text-sm">Run configuration</h2>
          </div>
          <div className="p-5 space-y-5">
            {/* Run type */}
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-2">Run type</label>
              <div className="grid grid-cols-3 gap-2">
                {(["regular", "arrear", "increment_arrear"] as const).map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setRunType(t)}
                    className={`rounded-lg border px-3 py-2.5 text-xs font-medium transition-colors ${
                      runType === t
                        ? "border-brand-500 bg-brand-50 text-brand-700"
                        : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                    }`}
                  >
                    {t === "regular" ? "Regular" : t === "arrear" ? "Arrear" : "Increment arrear"}
                  </button>
                ))}
              </div>
            </div>

            {/* Period month */}
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">
                Period month
                <span className="ml-1 text-xs text-slate-400 font-normal">(YYYY-MM-DD of first day)</span>
              </label>
              <input
                type="date"
                className="w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent"
                value={periodMonth}
                onChange={(e) => setPeriodMonth(e.target.value)}
              />
              <p className="text-xs text-slate-400 mt-1.5 flex items-center gap-1">
                <Info size={11} /> Used to store the register and compare with prior month.
              </p>
            </div>

            {/* Arrear dates */}
            {needsArrearDates && (
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1.5">Effective from</label>
                  <input
                    type="date"
                    className="w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent"
                    value={from}
                    onChange={(e) => setFrom(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1.5">Effective to</label>
                  <input
                    type="date"
                    className="w-full rounded-lg border border-slate-300 px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent"
                    value={to}
                    onChange={(e) => setTo(e.target.value)}
                  />
                </div>
              </div>
            )}

            {/* Strict check */}
            <label className="flex items-start gap-3 cursor-pointer group">
              <div className="relative mt-0.5 flex-shrink-0">
                <input
                  type="checkbox"
                  checked={strict}
                  onChange={(e) => setStrict(e.target.checked)}
                  className="sr-only"
                />
                <div className={`w-4 h-4 rounded border-2 flex items-center justify-center transition-colors ${strict ? "border-brand-600 bg-brand-600" : "border-slate-300 bg-white"}`}>
                  {strict && <CheckCircle2 size={10} className="text-white" />}
                </div>
              </div>
              <div>
                <p className="text-sm font-medium text-slate-800">Strict header check</p>
                <p className="text-xs text-slate-500 mt-0.5">All configured salary components must exist as columns.</p>
              </div>
            </label>

            {/* Parse button */}
            <button
              type="button"
              disabled={!file || busy}
              onClick={() => void parseUpload()}
              className="flex items-center gap-2 rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50 transition-colors"
            >
              {busy ? (
                <span className="flex items-center gap-2">
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Parsing…
                </span>
              ) : (
                <>
                  <Play size={14} /> Parse & preview
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {/* Alerts */}
      {error && (
        <div className="flex items-start gap-3 rounded-xl bg-danger-50 border border-danger-200 text-danger-700 px-4 py-3.5 text-sm">
          <AlertTriangle size={16} className="flex-shrink-0 mt-0.5" />
          {error}
        </div>
      )}
      {missing.length > 0 && (
        <div className="rounded-xl bg-amber-50 border border-amber-200 px-4 py-3.5">
          <div className="flex items-center gap-2 text-amber-800 font-semibold text-sm mb-2">
            <AlertTriangle size={15} /> Missing required columns
          </div>
          <div className="flex flex-wrap gap-1.5">
            {missing.map((m) => (
              <span key={m} className="rounded-md bg-amber-100 text-amber-800 px-2 py-0.5 text-xs font-medium">{m}</span>
            ))}
          </div>
        </div>
      )}
      {warnings.length > 0 && (
        <div className="rounded-xl bg-slate-50 border border-slate-200 px-4 py-3.5">
          <div className="flex items-center gap-2 text-slate-700 font-semibold text-sm mb-2">
            <HelpCircle size={15} /> Warnings
          </div>
          <ul className="space-y-1">
            {warnings.map((w) => (
              <li key={w} className="text-xs text-slate-600 flex items-start gap-1.5">
                <ChevronRight size={11} className="mt-0.5 flex-shrink-0 text-slate-400" />{w}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Step 2: Preview + Validate */}
      {step >= 2 && employees.length > 0 && (
        <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CheckCircle2 size={16} className="text-success-600" />
              <p className="font-semibold text-slate-900 text-sm">
                {employees.length} employees parsed
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400">{columns.length} columns</span>
              <button
                type="button"
                disabled={!employees.length || busy}
                onClick={() => void runValidate()}
                className="flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-50 transition-colors shadow-sm"
              >
                {busy ? "Validating…" : (
                  <>
                    <ShieldCheck size={14} /> Run validation
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Columns detected */}
          <div className="px-5 py-3 border-b border-slate-100 bg-slate-50/40">
            <p className="text-xs text-slate-500 font-medium mb-1.5">Columns detected</p>
            <div className="flex flex-wrap gap-1">
              {columns.map((c) => (
                <span key={c} className="rounded-md bg-slate-100 text-slate-700 px-2 py-0.5 text-[11px] font-medium">{c}</span>
              ))}
            </div>
          </div>

          {/* Preview table */}
          {preview.length > 0 && (
            <div className="overflow-x-auto">
              <p className="px-5 py-2 text-xs text-slate-500 font-medium border-b border-slate-100">Preview (first {preview.length} rows)</p>
              <table className="min-w-full text-xs">
                <thead className="bg-slate-50 text-left text-slate-500 border-b border-slate-100">
                  <tr>
                    {Object.keys(preview[0]).map((k) => (
                      <th key={k} className="px-4 py-2 font-semibold whitespace-nowrap">{k}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.map((row, idx) => (
                    <tr key={idx} className="border-b border-slate-50">
                      {Object.values(row).map((v, i) => (
                        <td key={i} className="px-4 py-2 text-slate-700 whitespace-nowrap">{String(v ?? "")}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ShieldCheck({ size, className }: { size: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      <polyline points="9 12 11 14 15 10" />
    </svg>
  );
}
