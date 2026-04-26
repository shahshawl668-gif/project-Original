"use client";

import { apiFetch } from "@/lib/api";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

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
    const res = await apiFetch("/api/ctc/uploads");
    if (!res.ok) {
      setError("Failed to load uploads");
      setLoading(false);
      return;
    }
    setUploads(await res.json());
    setError(null);
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const open = async (id: string) => {
    setActiveId(id);
    const res = await apiFetch(`/api/ctc/uploads/${id}`);
    if (!res.ok) {
      setError("Failed to load records");
      return;
    }
    setRecords(await res.json());
  };

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">CTC history</h1>
          <p className="text-sm text-slate-600 mt-1">All CTC uploads, used for increment-arrears validation.</p>
        </div>
        <Link href="/ctc/upload" className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white">
          Upload new
        </Link>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="rounded-lg border border-slate-200 bg-white overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-3 py-2">Effective from</th>
              <th className="px-3 py-2">File</th>
              <th className="px-3 py-2">Employees</th>
              <th className="px-3 py-2">Uploaded at</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-slate-500">
                  Loading…
                </td>
              </tr>
            ) : uploads.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-slate-500">
                  No CTC uploads yet.
                </td>
              </tr>
            ) : (
              uploads.map((u) => (
                <tr key={u.id} className="border-t border-slate-100">
                  <td className="px-3 py-2 font-medium">{u.effective_from}</td>
                  <td className="px-3 py-2">{u.filename || "—"}</td>
                  <td className="px-3 py-2">{u.employee_count ?? "—"}</td>
                  <td className="px-3 py-2 text-slate-600">{new Date(u.created_at).toLocaleString()}</td>
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      className="text-brand-700 hover:underline"
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

      {activeId && records.length > 0 && (
        <div className="rounded-lg border border-slate-200 bg-white overflow-x-auto">
          <div className="px-4 py-3 border-b border-slate-100 text-sm font-medium text-slate-900">
            Records ({records.length})
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
              {records.map((r) => (
                <tr key={r.id} className="border-t border-slate-100 align-top">
                  <td className="px-2 py-2 font-medium">{r.employee_id}</td>
                  <td className="px-2 py-2">{r.employee_name || "—"}</td>
                  <td className="px-2 py-2">{r.effective_from}</td>
                  <td className="px-2 py-2">{r.annual_ctc ?? "—"}</td>
                  <td className="px-2 py-2 text-slate-600">
                    {Object.entries(r.annual_components)
                      .map(([k, v]) => `${k}: ${v}`)
                      .join(", ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
