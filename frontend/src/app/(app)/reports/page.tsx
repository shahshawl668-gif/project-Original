"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, EyeOff, FileSpreadsheet, Loader2 } from "lucide-react";

import { Menu, MenuItem } from "@/components/cost/Menu";
import { ActiveFilters, FilterMenu } from "@/components/cost/FilterMenu";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiBlob } from "@/lib/api";
import {
  fetchDimensions,
  fetchPeriods,
  fetchReports,
  type ReportMeta,
} from "@/lib/cost-analysis";
import { cn } from "@/lib/utils";

/**
 * Report downloads.
 *
 * Every workbook carries a provenance sheet — what it covered, which filters
 * were applied, how fresh the data was, who generated it and when — so a report
 * that circulates by email can still answer those questions in November.
 */
export default function ReportsPage() {
  const [groupBy, setGroupBy] = useState("department");
  const [filters, setFilters] = useState<Record<string, string[]>>({});
  const [masked, setMasked] = useState(false);
  const [dateFrom, setDateFrom] = useState<string | null>(null);
  const [dateTo, setDateTo] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reports = useQuery({ queryKey: ["reports"], queryFn: fetchReports });
  const dims = useQuery({ queryKey: ["bi", "dimensions"], queryFn: fetchDimensions });
  const periods = useQuery({ queryKey: ["bi", "periods"], queryFn: fetchPeriods });
  const available = periods.data?.periods ?? [];

  function toggleFilter(key: string, value: string) {
    setFilters((current) => {
      const existing = current[key] ?? [];
      const next = existing.includes(value)
        ? existing.filter((v) => v !== value)
        : [...existing, value];
      const out = { ...current, [key]: next };
      if (!next.length) delete out[key];
      return out;
    });
  }

  async function download(report: ReportMeta) {
    setBusy(report.key);
    setError(null);
    try {
      const params = new URLSearchParams({ group_by: groupBy });
      if (dateFrom) params.set("date_from", dateFrom);
      if (dateTo) params.set("date_to", dateTo);
      for (const [key, values] of Object.entries(filters)) {
        for (const value of values) params.append(key, value);
      }
      const blob = await apiBlob(`/api/reports/${report.key}.xlsx?${params}`, {
        headers: masked ? { "X-Mask-Identity": "on" } : undefined,
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${report.key}.xlsx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Reports"
        title="Download a report"
        description="Every workbook opens with where it came from: the period it covers, the filters applied, how fresh the registers were, and who generated it. Reports are built from the same figures as the dashboards, so the two can never disagree."
      />

      <Card>
        <CardContent className="space-y-3 py-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Menu
              label="Break down by"
              summary={dims.data?.dimensions.find((d) => d.key === groupBy)?.label ?? "Department"}
            >
              {(close) =>
                (dims.data?.dimensions ?? []).map((dimension) => (
                  <MenuItem
                    key={dimension.key}
                    selected={dimension.key === groupBy}
                    onClick={() => { setGroupBy(dimension.key); close(); }}
                  >
                    {dimension.label}
                  </MenuItem>
                ))
              }
            </Menu>

            <Menu
              label="From"
              summary={available.find((p) => p.period === dateFrom)?.label ?? "Earliest"}
              width="w-44"
            >
              {(close) => (
                <>
                  <MenuItem selected={!dateFrom} onClick={() => { setDateFrom(null); close(); }}>
                    Earliest stored
                  </MenuItem>
                  {available.map((option) => (
                    <MenuItem
                      key={option.period}
                      selected={option.period === dateFrom}
                      onClick={() => { setDateFrom(option.period); close(); }}
                    >
                      {option.label}
                    </MenuItem>
                  ))}
                </>
              )}
            </Menu>

            <Menu
              label="To"
              summary={available.find((p) => p.period === dateTo)?.label ?? "Latest"}
              width="w-44"
            >
              {(close) => (
                <>
                  <MenuItem selected={!dateTo} onClick={() => { setDateTo(null); close(); }}>
                    Latest stored
                  </MenuItem>
                  {available.map((option) => (
                    <MenuItem
                      key={option.period}
                      selected={option.period === dateTo}
                      onClick={() => { setDateTo(option.period); close(); }}
                    >
                      {option.label}
                    </MenuItem>
                  ))}
                </>
              )}
            </Menu>

            <FilterMenu
              dimensions={dims.data?.dimensions ?? []}
              filters={filters}
              onToggle={toggleFilter}
              onClear={() => setFilters({})}
            />
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-ink-100 pt-3 dark:border-white/5">
            <ActiveFilters
              dimensions={dims.data?.dimensions ?? []}
              filters={filters}
              onToggle={toggleFilter}
              onClear={() => setFilters({})}
            />
            <button
              type="button"
              onClick={() => setMasked((v) => !v)}
              aria-pressed={masked}
              className={cn(
                "ml-auto inline-flex h-9 items-center gap-1.5 rounded-lg border px-3 text-sm font-medium transition-colors",
                masked
                  ? "border-brand-500 bg-brand-600 text-white"
                  : "border-ink-200 bg-white text-ink-700 hover:bg-ink-50 dark:border-white/10 dark:bg-white/[0.04] dark:text-ink-200 dark:hover:bg-white/[0.07]",
              )}
            >
              <EyeOff size={14} />
              {masked ? "Names masked" : "Mask names"}
            </button>
          </div>
          <p className="text-xs text-ink-500 dark:text-ink-400">
            Masking replaces each name with a stable per-workspace token and initials. The
            figures are unchanged — it is for a report that will be forwarded further than the
            people who may see who earns what.
          </p>
        </CardContent>
      </Card>

      {error && (
        <AlertBanner variant="error" title="Could not generate that report">{error}</AlertBanner>
      )}

      {reports.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-28" />)}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {(reports.data?.reports ?? []).map((report) => (
            <Card key={report.key}>
              <CardContent className="flex h-full flex-col gap-2 py-4">
                <span className="flex items-center gap-2 text-sm font-semibold text-ink-900 dark:text-white">
                  <FileSpreadsheet size={15} className="text-brand-600 dark:text-brand-400" />
                  {report.title}
                </span>
                <p className="flex-1 text-xs text-ink-500 dark:text-ink-400">
                  {report.description}
                </p>
                <button
                  type="button"
                  onClick={() => download(report)}
                  disabled={busy === report.key}
                  className="mt-1 inline-flex items-center justify-center gap-1.5 rounded-lg border border-ink-200 px-3 py-1.5 text-xs font-medium text-ink-700 transition-colors hover:bg-ink-50 disabled:opacity-60 dark:border-white/10 dark:text-ink-200 dark:hover:bg-white/[0.06]"
                >
                  {busy === report.key ? (
                    <><Loader2 size={13} className="animate-spin" /> Building…</>
                  ) : (
                    <><Download size={13} /> Download .xlsx</>
                  )}
                </button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
