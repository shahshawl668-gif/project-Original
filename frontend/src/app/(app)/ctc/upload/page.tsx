"use client";

import { apiFetch, apiJson, parseEnvelopeResponse } from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import Link from "next/link";
import { useCallback, useState } from "react";
import { toast } from "sonner";
import { ArrowRight, CloudUpload, FileSpreadsheet, Table2, Trash2 } from "lucide-react";

type CtcRow = {
  employee_id: string;
  employee_name: string | null;
  effective_from: string;
  annual_components: { [k: string]: number };
  annual_ctc: number;
};

export default function CtcUploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [defaultEff, setDefaultEff] = useState("");
  const [columns, setColumns] = useState<string[]>([]);
  const [records, setRecords] = useState<CtcRow[]>([]);
  const [unknown, setUnknown] = useState<string[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [committedId, setCommittedId] = useState<string | null>(null);

  const reset = (f: File | null) => {
    setFile(f);
    setRecords([]);
    setColumns([]);
    setUnknown([]);
    setWarnings([]);
    setError(null);
    setCommittedId(null);
  };

  const parse = useCallback(async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("meta", JSON.stringify({ default_effective_from: defaultEff || null }));
    const res = await apiFetch("/api/ctc/upload", { method: "POST", body: fd });
    try {
      const data = await parseEnvelopeResponse<{
        columns: string[];
        records: CtcRow[];
        unknown_columns?: string[];
        warnings?: string[];
      }>(res);
      setColumns(data.columns);
      setRecords(data.records);
      setUnknown(data.unknown_columns || []);
      setWarnings(data.warnings || []);
      toast.success("File parsed successfully", {
        description: `${data.records.length.toLocaleString("en-IN")} rows ready to review.`,
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Parse failed";
      setError(msg);
      toast.error("Parse failed", { description: msg });
    }
    setBusy(false);
  }, [file, defaultEff]);

  const commit = async () => {
    if (!records.length) return;
    setBusy(true);
    setError(null);
    try {
      const data = await apiJson<{ id: string }>("/api/ctc/commit", {
        method: "POST",
        body: JSON.stringify({
          filename: file?.name || null,
          default_effective_from: defaultEff || null,
          records,
        }),
      });
      setCommittedId(data.id);
      toast.success("CTC snapshot saved", {
        description: `${records.length.toLocaleString("en-IN")} employees committed to history.`,
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Commit failed";
      setError(msg);
      toast.error("Could not commit CTC", { description: msg });
    }
    setBusy(false);
  };

  const clearFile = () => reset(null);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Upload CTC"
        description={
          <>
            Import annual cost‑to‑company by employee. Uses{" "}
            <code className="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs font-semibold text-slate-700">
              employee_id
            </code>
            ,{" "}
            <code className="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs font-semibold text-slate-700">
              effective_from
            </code>
            , and annual amounts per configured component (CSV or Excel).
          </>
        }
        actions={
          <Button variant="outline" asChild>
            <Link href="/ctc/history" className="gap-2">
              CTC history <ArrowRight size={14} />
            </Link>
          </Button>
        }
      />

      {error ? (
        <AlertBanner variant="error" title="Something went wrong">
          {error}
        </AlertBanner>
      ) : null}

      {committedId ? (
        <AlertBanner variant="success" title="Upload saved">
          Linked to history record{" "}
          <span className="font-mono text-sm font-semibold">{committedId.slice(0, 8)}…</span>.{" "}
          <Link href="/ctc/history" className="font-semibold text-emerald-900 underline underline-offset-2">
            Open CTC history
          </Link>
        </AlertBanner>
      ) : null}

      <Card className="overflow-hidden">
        <CardContent className="p-0">
          <div
            className={`relative border-b border-slate-100 px-6 py-14 text-center transition-all ${
              drag ? "bg-brand-50/80 ring-2 ring-brand-400/40 ring-inset" : "bg-slate-50/50"
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
              if (f) reset(f);
            }}
          >
            <div className="mx-auto flex max-w-md flex-col items-center">
              <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-white shadow-soft ring-1 ring-slate-900/[0.06]">
                <CloudUpload className="h-7 w-7 text-brand-600" strokeWidth={1.75} />
              </div>
              <p className="text-sm font-semibold text-slate-900">Drag and drop your file</p>
              <p className="mt-1 text-sm text-slate-600">or choose a CSV / Excel spreadsheet from your device</p>
              <label className="mt-6 inline-flex cursor-pointer items-center rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white shadow-soft transition hover:bg-brand-700">
                <input
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  className="hidden"
                  onChange={(e) => reset(e.target.files?.[0] || null)}
                />
                Browse files
              </label>
              {file ? (
                <div className="mt-6 flex flex-wrap items-center justify-center gap-2 text-xs text-slate-600">
                  <span className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 font-medium shadow-sm ring-1 ring-slate-200/80">
                    <FileSpreadsheet size={14} className="text-brand-600" />
                    {file.name}
                  </span>
                  <button
                    type="button"
                    onClick={clearFile}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 font-medium text-slate-600 transition hover:bg-slate-50"
                  >
                    <Trash2 size={13} /> Remove
                  </button>
                </div>
              ) : null}
            </div>
          </div>

          <div className="space-y-6 p-6 sm:p-8">
            <div className="grid gap-6 sm:grid-cols-2">
              <label className="block">
                <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Default effective from</span>
                <input
                  type="date"
                  className="mt-2 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-medium text-slate-900 shadow-sm outline-none ring-brand-500/20 transition-shadow focus-visible:ring-[3px]"
                  value={defaultEff}
                  onChange={(e) => setDefaultEff(e.target.value)}
                />
                <span className="mt-2 block text-xs leading-relaxed text-slate-500">
                  Applied when a row omits <code className="font-mono text-2xs">effective_from</code>.
                </span>
              </label>
            </div>

            <div className="flex flex-wrap gap-3">
              <Button type="button" disabled={!file || busy} onClick={() => void parse()} className="rounded-xl px-5">
                {busy ? "Working…" : "Parse & preview"}
              </Button>
              <Button
                type="button"
                variant="secondary"
                disabled={!records.length || busy}
                onClick={() => void commit()}
                className="rounded-xl px-5"
              >
                Commit to history
              </Button>
            </div>

            {unknown.length > 0 ? (
              <AlertBanner variant="warning" title="Unknown columns ignored">
                <span className="break-all text-xs">{unknown.join(", ")}</span>
              </AlertBanner>
            ) : null}

            {warnings.length > 0 ? (
              <AlertBanner variant="info" title="Parser notices">
                <ul className="mt-2 list-inside list-disc space-y-1 text-xs">
                  {warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </AlertBanner>
            ) : null}
          </div>
        </CardContent>
      </Card>

      {busy && columns.length === 0 && records.length === 0 ? (
        <Card>
          <CardContent className="space-y-3 p-6">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-4 w-full max-w-xl" />
            <Skeleton className="h-4 w-full max-w-lg" />
          </CardContent>
        </Card>
      ) : null}

      {!busy && columns.length > 0 ? (
        <Card>
          <CardContent className="border-b border-slate-100 p-5">
            <div className="flex items-center gap-2">
              <Table2 size={17} className="text-slate-500" />
              <div>
                <h2 className="text-sm font-semibold text-slate-900">Columns detected</h2>
                <p className="text-xs text-slate-500">Mapped headers from your file</p>
              </div>
            </div>
          </CardContent>
          <CardContent className="p-5">
            <p className="break-all font-mono text-xs leading-relaxed text-slate-700">{columns.join(", ")}</p>
          </CardContent>
        </Card>
      ) : null}

      {!busy && records.length > 0 ? (
        <Card className="overflow-hidden">
          <CardContent className="flex flex-wrap items-end justify-between gap-3 border-b border-slate-100 p-5">
            <div>
              <h2 className="text-sm font-semibold text-slate-900">Preview</h2>
              <p className="text-xs text-slate-500">
                Showing first {Math.min(25, records.length)} of {records.length.toLocaleString("en-IN")} rows
              </p>
            </div>
          </CardContent>
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead className="sticky top-0 bg-slate-50/95 text-left text-2xs font-semibold uppercase tracking-wide text-slate-500 backdrop-blur">
                <tr>
                  <th className="whitespace-nowrap px-4 py-3 font-semibold">employee_id</th>
                  <th className="whitespace-nowrap px-4 py-3 font-semibold">name</th>
                  <th className="whitespace-nowrap px-4 py-3 font-semibold">effective_from</th>
                  <th className="whitespace-nowrap px-4 py-3 font-semibold">annual_ctc</th>
                  <th className="whitespace-nowrap px-4 py-3 font-semibold">components</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {records.slice(0, 25).map((r) => (
                  <tr key={`${r.employee_id}-${r.effective_from}`} className="align-top hover:bg-slate-50/60">
                    <td className="whitespace-nowrap px-4 py-2.5 font-semibold text-slate-900">{r.employee_id}</td>
                    <td className="px-4 py-2.5 text-slate-700">{r.employee_name || "—"}</td>
                    <td className="whitespace-nowrap px-4 py-2.5 text-slate-600">{r.effective_from}</td>
                    <td className="whitespace-nowrap px-4 py-2.5 tabular-nums text-slate-800">{r.annual_ctc}</td>
                    <td className="min-w-[12rem] px-4 py-2.5 text-slate-600">
                      {Object.entries(r.annual_components)
                        .map(([k, v]) => `${k}: ${v}`)
                        .join(", ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : !busy && file && columns.length === 0 && records.length === 0 && !error ? (
        <EmptyState
          icon={<FileSpreadsheet className="h-6 w-6 text-slate-400" />}
          title="Ready to parse"
          description="Run “Parse & preview” to validate column mapping and preview rows before committing."
          className="bg-white"
        />
      ) : null}
    </div>
  );
}
