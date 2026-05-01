"use client";

import { apiJson } from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { CalendarDays, Users, FileText, ChevronRight, Download, Search } from "lucide-react";

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

export default function RegisterHistoryContent() {
  const searchParams = useSearchParams();
  const initialId = searchParams.get("id");

  const [registers, setRegisters] = useState<Register[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(initialId);
  const [detail, setDetail] = useState<RegisterDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const openRegister = useCallback(async (id: string) => {
    setActiveId(id);
    setDetailLoading(true);
    setSearch("");
    try {
      setDetail(await apiJson<RegisterDetail>(`/api/payroll/registers/${id}`));
    } catch {
      setError("Failed to load register detail.");
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiJson<Register[]>("/api/payroll/registers");
      setRegisters(data);
      setError(null);
      if (initialId && data.some((r) => r.id === initialId)) {
        await openRegister(initialId);
      }
    } catch {
      setError("Failed to load stored registers.");
    } finally {
      setLoading(false);
    }
  }, [initialId, openRegister]);

  useEffect(() => {
    void load();
  }, [load]);

  const fmtMonth = (iso: string) =>
    new Date(iso + (iso.length === 7 ? "-01" : "")).toLocaleDateString("en-IN", {
      month: "long",
      year: "numeric",
    });

  const fmtDate = (iso: string) =>
    new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });

  const downloadCsv = () => {
    if (!detail) return;
    const headers = ["employee_id", "employee_name", "paid_days", "lop_days"];
    const compKeys = detail.rows.length > 0 ? Object.keys(detail.rows[0].components) : [];
    const arrearKeys = detail.rows.length > 0 ? Object.keys(detail.rows[0].arrears || {}) : [];
    const allHeaders = [
      ...headers,
      ...compKeys,
      ...arrearKeys.map((k) => `${k}_arrear`),
      "increment_arrear_total",
    ];
    const lines = [allHeaders.join(",")];
    for (const row of detail.rows) {
      const vals = [
        row.employee_id,
        row.employee_name ?? "",
        row.paid_days ?? "",
        row.lop_days ?? "",
        ...compKeys.map((k) => row.components[k] ?? 0),
        ...arrearKeys.map((k) => row.arrears?.[k] ?? 0),
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
    <div className="space-y-8">
      <PageHeader
        title="Payroll history"
        description={
          <>
            Salary registers keyed by calendar month; re-uploading the same{" "}
            <code className="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs font-semibold text-slate-700">
              period_month
            </code>{" "}
            replaces the prior snapshot for that tenant.
          </>
        }
        actions={
          <Button asChild className="rounded-xl shadow-soft">
            <Link href="/payroll/upload">
              <FileText size={16} strokeWidth={2} /> New upload
            </Link>
          </Button>
        }
      />

      {error ? (
        <AlertBanner variant="error" title="We hit a snag">
          {error}
        </AlertBanner>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="flex min-h-[22rem] flex-col overflow-hidden">
          <div className="border-b border-slate-100 px-5 py-4">
            <p className="text-2xs font-semibold uppercase tracking-widest text-slate-400">Registers</p>
            <p className="mt-1 text-sm font-semibold text-slate-900">
              {loading ? "Loading…" : `${registers.length} stored`}
            </p>
          </div>

          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <div className="space-y-0 p-2">
                {[1, 2, 3, 4, 5, 6].map((i) => (
                  <div key={i} className="flex items-center gap-3 px-3 py-3">
                    <Skeleton className="h-10 w-10 shrink-0 rounded-xl" />
                    <div className="min-w-0 flex-1 space-y-2">
                      <Skeleton className="h-4 w-32" />
                      <Skeleton className="h-3 w-24" />
                    </div>
                  </div>
                ))}
              </div>
            ) : registers.length === 0 ? (
              <div className="p-4">
                <EmptyState
                  icon={<CalendarDays className="h-6 w-6 text-slate-400" />}
                  title="No registers stored"
                  description="Upload payroll with an explicit period so we can normalize rows for auditing."
                  action={
                    <Button asChild variant="outline" className="rounded-xl">
                      <Link href="/payroll/upload">Go to upload</Link>
                    </Button>
                  }
                  className="border-0 bg-transparent py-8"
                />
              </div>
            ) : (
              <div className="scrollbar-thin divide-y divide-slate-100">
                {registers.map((reg) => (
                  <button
                    key={reg.id}
                    type="button"
                    onClick={() => void openRegister(reg.id)}
                    className={`flex w-full items-center gap-3 px-4 py-3.5 text-left transition-colors hover:bg-slate-50 ${
                      activeId === reg.id ? "border-l-[3px] border-brand-600 bg-brand-50/50" : ""
                    }`}
                  >
                    <div
                      className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
                        activeId === reg.id ? "bg-white shadow-sm ring-1 ring-brand-600/15" : "bg-slate-100"
                      }`}
                    >
                      <CalendarDays
                        size={17}
                        className={activeId === reg.id ? "text-brand-700" : "text-slate-500"}
                        strokeWidth={1.75}
                      />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p
                        className={`truncate text-sm font-semibold ${activeId === reg.id ? "text-brand-900" : "text-slate-900"}`}
                      >
                        {fmtMonth(reg.period_month)}
                      </p>
                      <p className="mt-0.5 flex items-center gap-1 text-2xs font-medium uppercase tracking-wide text-slate-400">
                        <Users size={11} aria-hidden /> {reg.employee_count ?? "—"} employees
                      </p>
                    </div>
                    <ChevronRight size={15} className="shrink-0 text-slate-300" aria-hidden />
                  </button>
                ))}
              </div>
            )}
          </div>
        </Card>

        <Card className="min-h-[22rem] overflow-hidden lg:col-span-2">
          {!activeId ? (
            <CardContent className="flex min-h-[20rem] flex-col items-center justify-center p-8">
              <EmptyState
                icon={<FileText className="h-7 w-7 text-slate-400" strokeWidth={1.5} />}
                title="Select a register"
                description="Choose a pay month on the left to inspect validated rows and export CSV."
                className="border-0 bg-transparent"
              />
            </CardContent>
          ) : detailLoading ? (
            <div className="flex min-h-[20rem] flex-col border-b border-slate-100 px-6 py-5">
              <Skeleton className="h-6 w-48" />
              <Skeleton className="mt-3 h-3 w-full max-w-md" />
              <div className="mt-8 space-y-3">
                <Skeleton className="h-10 w-full rounded-xl" />
                {[1, 2, 3, 4, 5, 6].map((i) => (
                  <Skeleton key={i} className="h-11 w-full" />
                ))}
              </div>
            </div>
          ) : detail ? (
            <div className="flex min-h-[20rem] flex-col">
              <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 px-6 py-5">
                <div>
                  <h2 className="text-lg font-semibold tracking-tight text-slate-900">
                    {fmtMonth(detail.period_month)}
                  </h2>
                  <p className="mt-1 text-sm text-slate-600">
                    {detail.filename || "Manual upload"} · Stored{" "}
                    <span className="font-medium text-slate-800">{fmtDate(detail.created_at)}</span> ·{" "}
                    <span className="font-semibold text-slate-900">{detail.employee_count}</span> employees
                  </p>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  onClick={downloadCsv}
                  className="rounded-xl bg-white shadow-sm"
                >
                  <Download size={15} strokeWidth={2} /> Export CSV
                </Button>
              </div>

              <div className="border-b border-slate-100 px-6 py-3">
                <div className="relative">
                  <Search
                    size={16}
                    className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400"
                    aria-hidden
                  />
                  <input
                    type="search"
                    placeholder="Search by employee ID or name…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className="h-10 w-full rounded-xl border border-slate-200 bg-slate-50/80 py-2 pl-10 pr-4 text-sm font-medium outline-none ring-brand-500/20 placeholder:text-slate-400 focus:border-brand-400 focus:bg-white focus:ring-[3px]"
                  />
                </div>
              </div>

              <div className="scrollbar-thin flex-1 overflow-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="sticky top-0 z-10 bg-slate-50/95 text-left text-2xs font-semibold uppercase tracking-wide text-slate-500 backdrop-blur">
                      <th className="whitespace-nowrap px-5 py-3 font-semibold">Employee</th>
                      <th className="whitespace-nowrap px-5 py-3 font-semibold">Paid / LOP</th>
                      {compKeys.map((k) => (
                        <th key={k} className="whitespace-nowrap px-5 py-3 font-semibold capitalize">
                          {k.replace(/_/g, " ")}
                        </th>
                      ))}
                      {detail.rows.some((r) => r.increment_arrear_total > 0) && (
                        <th className="whitespace-nowrap px-5 py-3 font-semibold">Inc. arrear</th>
                      )}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {filteredRows.length === 0 ? (
                      <tr>
                        <td
                          colSpan={3 + compKeys.length + (detail.rows.some((r) => r.increment_arrear_total > 0) ? 1 : 0)}
                          className="px-5 py-12 text-center"
                        >
                          <EmptyState
                            title={search ? "No matching employees" : "No rows"}
                            description={
                              search ? "Adjust your filters or choose another register." : "This register returned no normalized rows."
                            }
                            className="border-0 bg-transparent py-4"
                          />
                        </td>
                      </tr>
                    ) : (
                      filteredRows.map((row, idx) => (
                        <tr
                          key={row.employee_id}
                          className={`transition-colors hover:bg-brand-50/25 ${idx % 2 === 0 ? "bg-white" : "bg-slate-50/35"}`}
                        >
                          <td className="whitespace-nowrap px-5 py-2.5">
                            <p className="font-semibold text-slate-900">{row.employee_id}</p>
                            {row.employee_name ? (
                              <p className="text-xs text-slate-500">{row.employee_name}</p>
                            ) : null}
                          </td>
                          <td className="whitespace-nowrap px-5 py-2.5 text-xs text-slate-600">
                            {row.paid_days != null ? (
                              <span>
                                <span className="font-semibold text-slate-900">{row.paid_days}</span>
                                {row.lop_days != null ? (
                                  <span className="text-slate-400"> / {row.lop_days} LOP</span>
                                ) : null}
                              </span>
                            ) : (
                              "—"
                            )}
                          </td>
                          {compKeys.map((k) => (
                            <td
                              key={k}
                              className="whitespace-nowrap px-5 py-2.5 text-right font-mono text-sm text-slate-800"
                            >
                              {row.components[k]?.toLocaleString("en-IN", {
                                maximumFractionDigits: 0,
                              }) ?? "—"}
                            </td>
                          ))}
                          {detail.rows.some((r) => r.increment_arrear_total > 0) && (
                            <td className="whitespace-nowrap px-5 py-2.5 text-right font-mono text-sm font-medium text-violet-800">
                              {row.increment_arrear_total > 0
                                ? row.increment_arrear_total.toLocaleString("en-IN", {
                                    maximumFractionDigits: 0,
                                  })
                                : "—"}
                            </td>
                          )}
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
              {detail.rows.length > 0 ? (
                <div className="border-t border-slate-100 px-6 py-2.5 text-2xs font-medium uppercase tracking-wide text-slate-400">
                  Showing {filteredRows.length} of {detail.rows.length} employees
                </div>
              ) : null}
            </div>
          ) : null}
        </Card>
      </div>
    </div>
  );
}
