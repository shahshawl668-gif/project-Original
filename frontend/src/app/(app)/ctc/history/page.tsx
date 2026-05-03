"use client";

import { apiJson } from "@/lib/api";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { AlertBanner } from "@/components/ui/alert-banner";
import { EmptyState } from "@/components/ui/empty-state";
import { FileSpreadsheet, UploadCloud } from "lucide-react";

type Upload = {
  id: string;
  effective_from: string;
  filename: string | null;
  employee_count: number | null;
  created_at: string;
};

type Record = {
  id: string;
  employee_id: string;
  employee_name: string | null;
  effective_from: string;
  annual_components: { [k: string]: number };
  annual_ctc: number | null;
};

export default function CtcHistoryPage() {
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [records, setRecords] = useState<Record[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiJson<Upload[]>("/api/ctc/uploads");
      setUploads(data);
      setError(null);
    } catch {
      setError("Failed to load uploads");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const open = async (id: string) => {
    setActiveId(id);
    try {
      setRecords(await apiJson<Record[]>(`/api/ctc/uploads/${id}`));
    } catch {
      setError("Failed to load records");
    }
  };

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="CTC archive"
        title="CTC history"
        description="All CTC uploads, used for increment arrear validation. Newest first."
        actions={
          <Button asChild>
            <Link href="/ctc/upload">
              <UploadCloud size={15} strokeWidth={2} /> Upload new
            </Link>
          </Button>
        }
      />

      {error && (
        <AlertBanner variant="error" title="Couldn't load CTC uploads">
          {error}
        </AlertBanner>
      )}

      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="bg-ink-50/80 text-left text-[11px] font-bold uppercase tracking-[0.12em] text-ink-500 dark:bg-white/[0.03] dark:text-ink-300">
                <th className="px-4 py-3">Effective from</th>
                <th className="px-4 py-3">File</th>
                <th className="px-4 py-3">Employees</th>
                <th className="px-4 py-3">Uploaded at</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100 dark:divide-white/[0.05]">
              {loading ? (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-12 text-center text-ink-500 dark:text-ink-400"
                  >
                    Loading…
                  </td>
                </tr>
              ) : uploads.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-6">
                    <EmptyState
                      icon={
                        <FileSpreadsheet className="h-6 w-6 text-brand-500 dark:text-brand-300" />
                      }
                      title="No CTC uploads yet"
                      description="Upload a CTC sheet to power increment-arrear validations and CTC history snapshots."
                      action={
                        <Button asChild>
                          <Link href="/ctc/upload">
                            <UploadCloud size={15} strokeWidth={2} /> Upload CTC
                          </Link>
                        </Button>
                      }
                      className="border-0 bg-transparent py-6"
                    />
                  </td>
                </tr>
              ) : (
                uploads.map((u) => (
                  <tr
                    key={u.id}
                    className={`transition-colors hover:bg-ink-50/60 dark:hover:bg-white/[0.04] ${
                      activeId === u.id
                        ? "bg-brand-50/60 dark:bg-brand-500/10"
                        : ""
                    }`}
                  >
                    <td className="px-4 py-3 font-medium text-ink-900 dark:text-white">
                      {u.effective_from}
                    </td>
                    <td className="px-4 py-3 text-ink-700 dark:text-ink-200">
                      {u.filename || "—"}
                    </td>
                    <td className="num px-4 py-3 text-ink-700 dark:text-ink-200">
                      {u.employee_count ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-ink-500 dark:text-ink-400">
                      {new Date(u.created_at).toLocaleString("en-IN", {
                        day: "2-digit",
                        month: "short",
                        year: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        className="text-xs font-semibold text-brand-700 transition-colors hover:text-brand-800 dark:text-brand-300 dark:hover:text-brand-200"
                        onClick={() => void open(u.id)}
                      >
                        {activeId === u.id ? "Reload" : "View"}
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {activeId && records.length > 0 && (
        <Card className="overflow-hidden">
          <CardContent className="border-b border-ink-100 px-6 py-4 dark:border-white/[0.06]">
            <p className="font-display text-sm font-bold text-ink-900 dark:text-white">
              Records ({records.length})
            </p>
            <p className="mt-1 text-xs text-ink-500 dark:text-ink-400">
              Annual CTC components per employee, snapshot from selected upload.
            </p>
          </CardContent>
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead className="bg-ink-50/80 text-left text-[10px] font-bold uppercase tracking-[0.12em] text-ink-500 dark:bg-white/[0.03] dark:text-ink-300">
                <tr>
                  <th className="px-3 py-2.5">employee_id</th>
                  <th className="px-3 py-2.5">name</th>
                  <th className="px-3 py-2.5">effective_from</th>
                  <th className="px-3 py-2.5">annual_ctc</th>
                  <th className="px-3 py-2.5">components</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100 dark:divide-white/[0.05]">
                {records.map((r) => (
                  <tr
                    key={r.id}
                    className="align-top transition-colors hover:bg-ink-50/60 dark:hover:bg-white/[0.04]"
                  >
                    <td className="px-3 py-2.5 font-mono font-medium text-ink-900 dark:text-white">
                      {r.employee_id}
                    </td>
                    <td className="px-3 py-2.5 text-ink-700 dark:text-ink-200">
                      {r.employee_name || "—"}
                    </td>
                    <td className="px-3 py-2.5 text-ink-500 dark:text-ink-400">
                      {r.effective_from}
                    </td>
                    <td className="num px-3 py-2.5 font-semibold text-ink-900 dark:text-white">
                      {r.annual_ctc ?? "—"}
                    </td>
                    <td className="px-3 py-2.5 text-ink-500 dark:text-ink-400">
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
      )}
    </div>
  );
}
