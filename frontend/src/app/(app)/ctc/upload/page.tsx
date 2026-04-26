"use client";

import { apiFetch } from "@/lib/api";
import Link from "next/link";
import { useCallback, useState } from "react";

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
    if (!res.ok) {
      setError((await res.json()).detail || "Parse failed");
      setBusy(false);
      return;
    }
    const data = await res.json();
    setColumns(data.columns);
    setRecords(data.records);
    setUnknown(data.unknown_columns || []);
    setWarnings(data.warnings || []);
    setBusy(false);
  }, [file, defaultEff]);

  const commit = async () => {
    if (!records.length) return;
    setBusy(true);
    setError(null);
    const res = await apiFetch("/api/ctc/commit", {
      method: "POST",
      body: JSON.stringify({
        filename: file?.name || null,
        default_effective_from: defaultEff || null,
        records,
      }),
    });
    if (!res.ok) {
      setError((await res.json()).detail || "Commit failed");
      setBusy(false);
      return;
    }
    const data = await res.json();
    setCommittedId(data.id);
    setBusy(false);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Upload CTC report</h1>
          <p className="text-sm text-slate-600 mt-1">
            CSV or Excel with <code className="text-xs bg-slate-100 px-1 rounded">employee_id</code>,
            <code className="text-xs bg-slate-100 px-1 rounded ml-1">effective_from</code>, and annual amounts
            for each configured component.
          </p>
        </div>
        <Link href="/ctc/history" className="text-brand-700 text-sm font-medium hover:underline">
          View history
        </Link>
      </div>

      <div
        className={`rounded-xl border-2 border-dashed px-6 py-10 text-center transition ${
          drag ? "border-brand-500 bg-brand-50" : "border-slate-300 bg-white"
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
        <p className="text-slate-700 text-sm">Drag & drop a .csv or .xlsx file, or choose a file.</p>
        <input
          type="file"
          accept=".csv,.xlsx,.xls"
          className="mt-4"
          onChange={(e) => reset(e.target.files?.[0] || null)}
        />
        {file && (
          <p className="mt-2 text-xs text-slate-500">
            Selected: <span className="font-medium">{file.name}</span>
          </p>
        )}
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-5 space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm text-slate-700">
            <span className="font-medium">Default effective from</span>
            <input
              type="date"
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              value={defaultEff}
              onChange={(e) => setDefaultEff(e.target.value)}
            />
            <span className="block text-xs text-slate-500 mt-1">
              Used for rows whose file lacks an effective_from column.
            </span>
          </label>
        </div>
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            disabled={!file || busy}
            onClick={() => void parse()}
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {busy ? "Working…" : "Parse & preview"}
          </button>
          <button
            type="button"
            disabled={!records.length || busy}
            onClick={() => void commit()}
            className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            Commit to history
          </button>
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        {committedId && (
          <p className="text-sm text-emerald-700">
            Saved {records.length} CTC records.{" "}
            <Link href="/ctc/history" className="underline">
              View history
            </Link>
            .
          </p>
        )}
        {unknown.length > 0 && (
          <div className="text-sm text-slate-700 bg-slate-50 border border-slate-200 rounded-md p-3">
            <p className="font-medium">Unknown columns ignored</p>
            <p className="text-xs mt-1 break-all">{unknown.join(", ")}</p>
          </div>
        )}
        {warnings.length > 0 && (
          <ul className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-md p-3 list-disc ml-5">
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        )}
      </div>

      {columns.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="text-sm font-semibold text-slate-900 mb-2">Columns detected</h2>
          <p className="text-xs text-slate-600 break-all">{columns.join(", ")}</p>
        </div>
      )}

      {records.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white overflow-x-auto">
          <div className="px-4 py-3 border-b border-slate-100 text-sm font-medium text-slate-900">
            Preview ({records.length} records)
          </div>
          <table className="min-w-full text-xs">
            <thead className="bg-slate-50 text-left text-slate-600">
              <tr>
                <th className="px-2 py-2">employee_id</th>
                <th className="px-2 py-2">name</th>
                <th className="px-2 py-2">effective_from</th>
                <th className="px-2 py-2">annual_ctc</th>
                <th className="px-2 py-2">components</th>
              </tr>
            </thead>
            <tbody>
              {records.slice(0, 25).map((r) => (
                <tr key={`${r.employee_id}-${r.effective_from}`} className="border-t border-slate-100 align-top">
                  <td className="px-2 py-2 font-medium">{r.employee_id}</td>
                  <td className="px-2 py-2">{r.employee_name || "—"}</td>
                  <td className="px-2 py-2">{r.effective_from}</td>
                  <td className="px-2 py-2">{r.annual_ctc}</td>
                  <td className="px-2 py-2 text-slate-600">
                    {Object.entries(r.annual_components)
                      .map(([k, v]) => `${k}: ${v}`)
                      .join(", ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {records.length > 25 && (
            <p className="px-4 py-2 text-xs text-slate-500">Showing first 25 of {records.length} rows.</p>
          )}
        </div>
      )}
    </div>
  );
}
