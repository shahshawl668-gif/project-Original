"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileSpreadsheet, Loader2, ShieldCheck, UploadCloud } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import {
  MASTER_TEMPLATE,
  commitMaster,
  fetchMasterUploads,
  previewMaster,
  type MasterPreview,
} from "@/lib/employee-master";
import { cn } from "@/lib/utils";

function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

/**
 * Employee master upload. Two steps like the attendance page: read the file and
 * show how every column was understood, then store it.
 */
export default function EmployeeMasterPage() {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [effective, setEffective] = useState(currentMonth());
  const [preview, setPreview] = useState<MasterPreview | null>(null);
  const [stored, setStored] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: uploads } = useQuery({ queryKey: ["master-uploads"], queryFn: fetchMasterUploads });

  const read = useMutation({
    mutationFn: () => previewMaster(file as File),
    onSuccess: (result) => {
      setError(null);
      setStored(null);
      setPreview(result);
    },
    onError: (err: Error) => {
      setPreview(null);
      setError(err.message);
    },
  });

  const store = useMutation({
    mutationFn: () => commitMaster(file as File, effective),
    onSuccess: (result) => {
      setError(null);
      const c = result.counts;
      setStored(
        `Stored ${result.employee_count ?? 0} employees effective ${result.effective_from.slice(0, 7)}` +
          (c ? ` — ${c.created} new, ${c.updated} changed, ${c.unchanged} unchanged.` : "."),
      );
      queryClient.invalidateQueries({ queryKey: ["master-uploads"] });
    },
    onError: (err: Error) => setError(err.message),
  });

  function pick(next: File | null) {
    setFile(next);
    setPreview(null);
    setStored(null);
    setError(null);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Employee master"
        description="Who works here and since when. Validation uses it to catch people paid before joining or after leaving, and people on the register who are not on the master."
      />

      {error && (
        <AlertBanner variant="error" title="That file could not be used">
          {error}
        </AlertBanner>
      )}
      {stored && (
        <AlertBanner variant="success" title="Stored">
          {stored} The next salary register validation will use it.
        </AlertBanner>
      )}

      <Card>
        <CardContent className="space-y-4 py-5">
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <span className="mb-1.5 block text-[11px] font-semibold text-ink-500">Effective from</span>
              <input
                type="month"
                value={effective}
                onChange={(event) => setEffective(event.target.value)}
                className="h-9 rounded-lg border border-ink-200 bg-white px-3 text-sm text-ink-900"
              />
            </div>
            <a
              href={`data:text/csv;charset=utf-8,${encodeURIComponent(MASTER_TEMPLATE)}`}
              download="employee-master-template.csv"
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-ink-200 px-3 text-sm font-medium text-ink-700 transition hover:bg-ink-50"
            >
              <Download size={14} /> Template
            </a>
          </div>

          <label
            className={cn(
              "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-ink-200 px-6 py-10 text-center transition hover:border-ink-300",
            )}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              pick(event.dataTransfer.files?.[0] ?? null);
            }}
          >
            {file ? (
              <>
                <FileSpreadsheet size={22} className="text-brand-600" />
                <span className="text-sm font-medium text-ink-900">{file.name}</span>
                <span className="text-xs text-ink-500">Choose another to replace it</span>
              </>
            ) : (
              <>
                <UploadCloud size={22} className="text-ink-500" />
                <span className="text-sm font-medium text-ink-800">Drop the employee master, or choose one</span>
                <span className="text-xs text-ink-500">.csv or .xlsx — id, name, joining and exit dates, state, gender</span>
              </>
            )}
            <input
              type="file"
              accept=".csv,.xlsx"
              className="hidden"
              onChange={(event) => pick(event.target.files?.[0] ?? null)}
            />
          </label>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => read.mutate()}
              disabled={!file || read.isPending}
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-brand-600 px-3 text-sm font-medium text-white transition hover:bg-brand-700 disabled:opacity-50"
            >
              {read.isPending ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />}
              Check the file
            </button>
            {preview && (
              <button
                type="button"
                onClick={() => store.mutate()}
                disabled={store.isPending || preview.row_count === 0}
                className="inline-flex h-9 items-center gap-2 rounded-lg border border-ink-200 px-3 text-sm font-medium text-ink-800 transition hover:bg-ink-50 disabled:opacity-50"
              >
                {store.isPending && <Loader2 size={14} className="animate-spin" />}
                Store {preview.row_count} employees
              </button>
            )}
          </div>
        </CardContent>
      </Card>

      {preview && (
        <Card>
          <CardContent className="space-y-3 py-5">
            <h2 className="text-sm font-semibold text-ink-900">How the file was read</h2>
            {preview.warnings.map((w) => (
              <AlertBanner key={w} variant="warning" title="Check this">
                {w}
              </AlertBanner>
            ))}
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(preview.header_map).map(([column, field]) => (
                <span key={column} className="rounded-full border border-ink-200 px-2 py-0.5 text-xs text-ink-700">
                  {column} → <b>{field}</b>
                </span>
              ))}
            </div>
            {preview.unmapped_columns.length > 0 && (
              <p className="text-xs text-ink-500">Ignored columns: {preview.unmapped_columns.join(", ")}</p>
            )}
            {preview.sample.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr>
                      {Object.keys(preview.sample[0]).map((k) => (
                        <th key={k} className="border-b border-ink-200 px-2 py-1 text-left font-medium text-ink-600">
                          {k}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.sample.map((row, i) => (
                      <tr key={i}>
                        {Object.values(row).map((v, j) => (
                          <td key={j} className="border-b border-ink-100 px-2 py-1 text-ink-800">
                            {v === null || v === "" ? "—" : String(v)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {uploads && uploads.length > 0 && (
        <Card>
          <CardContent className="py-5">
            <h2 className="mb-2 text-sm font-semibold text-ink-900">Stored versions</h2>
            <ul className="divide-y divide-ink-100 text-sm">
              {uploads.map((u) => (
                <li key={u.id} className="flex justify-between py-1.5">
                  <span className="text-ink-800">
                    Effective {u.effective_from.slice(0, 7)} · {u.employee_count ?? 0} employees
                  </span>
                  <span className="text-ink-500">{u.filename}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
