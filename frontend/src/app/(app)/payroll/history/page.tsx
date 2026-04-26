"use client";

import { apiFetch } from "@/lib/api";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  CalendarDays,
  Users,
  FileText,
  ChevronRight,
  Download,
  Search,
  ArrowLeft,
} from "lucide-react";

type Register = {
  id: string;
  period_month: string;
  filename: string | null;
  employee_count: number | null;
  created_at: string;
};

type RegisterRow = {
  employee_id: string;
  employee_name: string | null;
  paid_days: number | null;
  lop_days: number | null;
  components: Record<string, number>;
  arrears: Record<string, number>;
  increment_arrear_total: number;
};

type RegisterDetail = Register & { rows: RegisterRow[] };

export default function RegisterHistoryPage() {
  const searchParams = useSearchParams();
  const initialId = searchParams.get("id");

  const [registers, setRegisters] = useState<Register[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(initialId);
  const [detail, setDetail] = useState<RegisterDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    const res = await apiFetch("/api/payroll/registers");
    if (!res.ok) { setError("Failed to load registers"); setLoading(false); return; }
    const data: Register[] = await res.json();
    setRegisters(data);
    setError(null);
    setLoading(false);
    if (initialId && data.some((r) => r.id === initialId)) {
      void openRegister(initialId);
    }
  }, []); // eslint-disable-line

  const openRegister = async (id: string) => {
    setActiveId(id);
    setDetailLoading(true);
    setSearch("");
    const res = await apiFetch(`/api/payroll/registers/${id}`);
    if (!res.ok) { setError("Failed to load register detail"); setDetailLoading(false); return; }
    setDetail(await res.json());
    setDetailLoading(false);
  };

  useEffect(() => { void load(); }, [load]);

  const fmtMonth = (iso: string) =>
    new Date(iso + (iso.length === 7 ? "-01" : "")).toLocaleDateString("en-IN", {
      month: "long", year: "numeric",
    });

  const fmtDate = (iso: string) =>
    new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });

  const downloadCsv = () => {
    if (!detail) return;
    const headers = ["employee_id", "employee_name", "paid_days", "lop_days"];
    const compKeys = detail.rows.length > 0 ? Object.keys(detail.rows[0].components) : [];
    const arrearKeys = detail.rows.length > 0 ? Object.keys(detail.rows[0].arrears || {}) : [];
    const allHeaders = [...headers, ...compKeys, ...arrearKeys.map((k) => `${k}_arrear`), "increment_arrear_total"];
    const lines = [allHeaders.join(",")];
    for (const row of detail.rows) {
      const vals = [
        row.employee_id,
        row.employee_name ?? "",
        row.paid_days ?? "",
        row.lop_days ?? "",
        ...compKeys.map((k) => row.components[k] ?? 0),
        ...arrearKeys.map((k) => (row.arrears?.[k] ?? 0)),
        row.increment_arrear_total,
      ];
      lines.push(vals.map((v) => `"${v}"`).join(","));
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `register-${detail.period_month}.csv`;
    a.click();
  };

  const filteredRows = (detail?.rows ?? []).filter((r) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      r.employee_id.toLowerCase().includes(q) ||
      (r.employee_name?.toLowerCase().includes(q) ?? false)
    );
  });

  const compKeys = detail?.rows.length ? Object.keys(detail.rows[0].components) : [];

  return (
    <div className="space-y-6 max-w-7xl">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Register history</h1>
          <p className="text-sm text-slate-500 mt-1">
            All stored monthly salary registers. Each upload overwrites the same period.
          </p>
        </div>
        <Link
          href="/payroll/upload"
          className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 transition-colors flex items-center gap-2"
        >
          <FileText size={15} /> New upload
        </Link>
      </div>

      {error && (
        <div className="rounded-lg bg-danger-50 border border-danger-200 text-danger-700 px-4 py-3 text-sm">{error}</div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Register list */}
        <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-100 bg-slate-50/60">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Stored registers ({registers.length})
            </p>
          </div>
          {loading ? (
            <div className="py-10 text-center text-sm text-slate-400">Loading…</div>
          ) : registers.length === 0 ? (
            <div className="py-12 flex flex-col items-center text-center px-4">
              <CalendarDays size={28} className="text-slate-300 mb-2" />
              <p className="text-sm font-medium text-slate-600">No registers yet</p>
              <p className="text-xs text-slate-400 mt-1">Upload a payroll file with a period month.</p>
              <Link
                href="/payroll/upload"
                className="mt-3 text-xs text-brand-600 font-medium hover:underline"
              >
                Upload now →
              </Link>
            </div>
          ) : (
            <div className="divide-y divide-slate-50">
              {registers.map((reg) => (
                <button
                  key={reg.id}
                  type="button"
                  onClick={() => void openRegister(reg.id)}
                  className={`w-full flex items-center gap-3 px-4 py-3.5 text-left hover:bg-slate-50 transition-colors ${
                    activeId === reg.id ? "bg-brand-50 border-l-4 border-brand-600" : ""
                  }`}
                >
                  <div className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${
                    activeId === reg.id ? "bg-brand-100" : "bg-slate-100"
                  }`}>
                    <CalendarDays size={16} className={activeId === reg.id ? "text-brand-600" : "text-slate-500"} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className={`text-sm font-semibold ${activeId === reg.id ? "text-brand-700" : "text-slate-800"}`}>
                      {fmtMonth(reg.period_month)}
                    </p>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-[11px] text-slate-400 flex items-center gap-1">
                        <Users size={10} /> {reg.employee_count ?? "—"} employees
                      </span>
                    </div>
                  </div>
                  <ChevronRight size={14} className="text-slate-300 flex-shrink-0" />
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Register detail */}
        <div className="lg:col-span-2 rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
          {!activeId ? (
            <div className="flex flex-col items-center justify-center h-full min-h-[300px] text-center p-8">
              <div className="w-14 h-14 rounded-xl bg-slate-100 flex items-center justify-center mb-3">
                <FileText size={24} className="text-slate-300" />
              </div>
              <p className="text-sm font-medium text-slate-600">Select a register</p>
              <p className="text-xs text-slate-400 mt-1">Click a month on the left to view its employee rows.</p>
            </div>
          ) : detailLoading ? (
            <div className="flex items-center justify-center h-full min-h-[300px] text-sm text-slate-400">
              Loading rows…
            </div>
          ) : detail ? (
            <div>
              {/* Detail header */}
              <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between gap-3 flex-wrap">
                <div>
                  <h2 className="font-semibold text-slate-900">{fmtMonth(detail.period_month)}</h2>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {detail.filename || "Manual upload"} · Stored {fmtDate(detail.created_at)} ·{" "}
                    <span className="font-medium">{detail.employee_count}</span> employees
                  </p>
                </div>
                <button
                  type="button"
                  onClick={downloadCsv}
                  className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 transition-colors"
                >
                  <Download size={13} /> Export CSV
                </button>
              </div>

              {/* Search */}
              <div className="px-5 py-3 border-b border-slate-100">
                <div className="relative">
                  <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input
                    type="text"
                    placeholder="Search by employee ID or name…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className="w-full pl-8 pr-4 py-2 rounded-lg border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent"
                  />
                </div>
              </div>

              {/* Table */}
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="bg-slate-50 text-left text-xs font-semibold text-slate-500 border-b border-slate-100">
                      <th className="px-4 py-2.5 whitespace-nowrap sticky left-0 bg-slate-50">Employee</th>
                      <th className="px-4 py-2.5 whitespace-nowrap">Paid / LOP</th>
                      {compKeys.map((k) => (
                        <th key={k} className="px-4 py-2.5 whitespace-nowrap capitalize">
                          {k.replace(/_/g, " ")}
                        </th>
                      ))}
                      {detail.rows.some((r) => r.increment_arrear_total > 0) && (
                        <th className="px-4 py-2.5 whitespace-nowrap">Inc. Arrear</th>
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {filteredRows.length === 0 ? (
                      <tr>
                        <td colSpan={3 + compKeys.length} className="px-4 py-8 text-center text-slate-400 text-sm">
                          {search ? "No employees match your search." : "No rows in this register."}
                        </td>
                      </tr>
                    ) : (
                      filteredRows.map((row, idx) => (
                        <tr
                          key={row.employee_id}
                          className={`border-b border-slate-50 ${idx % 2 === 0 ? "bg-white" : "bg-slate-50/30"} hover:bg-brand-50/30 transition-colors`}
                        >
                          <td className="px-4 py-2.5 sticky left-0 bg-inherit">
                            <p className="font-medium text-slate-800 text-sm">{row.employee_id}</p>
                            {row.employee_name && (
                              <p className="text-[11px] text-slate-400">{row.employee_name}</p>
                            )}
                          </td>
                          <td className="px-4 py-2.5 text-xs text-slate-600 whitespace-nowrap">
                            {row.paid_days != null ? (
                              <span>
                                <span className="font-medium text-slate-800">{row.paid_days}</span>
                                {row.lop_days != null && (
                                  <span className="text-slate-400"> / {row.lop_days} LOP</span>
                                )}
                              </span>
                            ) : "—"}
                          </td>
                          {compKeys.map((k) => (
                            <td key={k} className="px-4 py-2.5 text-sm text-right font-mono text-slate-700 whitespace-nowrap">
                              {row.components[k]?.toLocaleString("en-IN", { maximumFractionDigits: 0 }) ?? "—"}
                            </td>
                          ))}
                          {detail.rows.some((r) => r.increment_arrear_total > 0) && (
                            <td className="px-4 py-2.5 text-sm text-right font-mono text-purple-700 whitespace-nowrap">
                              {row.increment_arrear_total > 0
                                ? row.increment_arrear_total.toLocaleString("en-IN", { maximumFractionDigits: 0 })
                                : "—"}
                            </td>
                          )}
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
              <div className="px-5 py-2 border-t border-slate-100 text-xs text-slate-400">
                Showing {filteredRows.length} of {detail.rows.length} employees
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
