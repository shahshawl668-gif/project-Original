"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Download, FileSpreadsheet, Loader2, SlidersHorizontal } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { ActiveFilters, FilterMenu } from "@/components/cost/FilterMenu";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { apiDownload } from "@/lib/api";
import { fetchDimensions, fetchPeriods, fetchReports, type ReportMeta } from "@/lib/cost-analysis";
import { saveBlob } from "@/lib/download";
import { plural } from "@/lib/format";
import { cn } from "@/lib/utils";

const FIELD = "h-9 w-full rounded-lg border border-ink-200 bg-white px-2.5 text-[13px] text-ink-900";
const BUILDER_ROLES = new Set(["owner", "manager", "analyst"]);

type Export =
  | { state: "running" }
  | { state: "done"; filename: string; bytes: number; at: Date }
  | { state: "failed"; message: string };

/**
 * The standard reports, grouped by the job each one does.
 *
 * One scope panel sets the period, breakdown, filters and name masking for
 * every report; each report then says which of those it actually reads (the
 * server declares it and its tests prove it), so nobody sets a filter and
 * receives a workbook it had no effect on. Every workbook opens with its own
 * provenance sheet.
 */
export default function ReportsPage() {
  const { entity, activeRole } = useEntity();
  const [groupBy, setGroupBy] = useState("department");
  const [filters, setFilters] = useState<Record<string, string[]>>({});
  const [masked, setMasked] = useState(false);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [exports, setExports] = useState<Record<string, Export>>({});
  const [announce, setAnnounce] = useState("");

  const reports = useQuery({ queryKey: ["reports", entity?.id], queryFn: fetchReports, enabled: !!entity });
  const dims = useQuery({ queryKey: ["bi", "dimensions", entity?.id], queryFn: fetchDimensions, enabled: !!entity });
  const periods = useQuery({ queryKey: ["bi", "periods", entity?.id], queryFn: fetchPeriods, enabled: !!entity });
  const available = periods.data?.periods ?? []; // newest first
  const dimensions = dims.data?.dimensions ?? [];
  const label = (p: string) => available.find((o) => o.period === p)?.label ?? p;
  const earliest = available.length ? available[available.length - 1].label : null;
  const latest = available.length ? available[0].label : null;
  const fromLabel = dateFrom ? label(dateFrom) : earliest ? `${earliest} (earliest)` : "Earliest stored";
  const toLabel = dateTo ? label(dateTo) : latest ? `${latest} (latest)` : "Latest stored";
  const reversed = !!dateFrom && !!dateTo && dateFrom > dateTo;
  const filterCount = Object.values(filters).reduce((n, v) => n + v.length, 0);
  const breakdownLabel = dimensions.find((d) => d.key === groupBy)?.label ?? "Department";

  function toggleFilter(key: string, value: string) {
    setFilters((current) => {
      const existing = current[key] ?? [];
      const next = existing.includes(value) ? existing.filter((v) => v !== value) : [...existing, value];
      const out = { ...current, [key]: next };
      if (!next.length) delete out[key];
      return out;
    });
  }

  async function download(report: ReportMeta) {
    setExports((e) => ({ ...e, [report.key]: { state: "running" } }));
    setAnnounce(`Generating ${report.title}`);
    try {
      const params = new URLSearchParams();
      if (report.inputs.breakdown) params.set("group_by", groupBy);
      if (dateFrom && report.inputs.period === "range") params.set("date_from", dateFrom);
      if (dateTo) params.set("date_to", dateTo);
      if (report.inputs.filters) {
        for (const [key, values] of Object.entries(filters)) for (const value of values) params.append(key, value);
      }
      const { blob, filename, bytes } = await apiDownload(`/api/reports/${report.key}.xlsx?${params}`, `${report.key}.xlsx`, {
        headers: masked && report.inputs.names ? { "X-Mask-Identity": "on" } : undefined,
      });
      saveBlob(blob, filename);
      setExports((e) => ({ ...e, [report.key]: { state: "done", filename, bytes, at: new Date() } }));
      setAnnounce(`${report.title} downloaded as ${filename}`);
    } catch (err) {
      const message = err instanceof Error ? err.message : "The server did not return a workbook.";
      setExports((e) => ({ ...e, [report.key]: { state: "failed", message } }));
      setAnnounce(`${report.title} failed: ${message}`);
    }
  }

  /** What this report will cover with the current scope, in words. */
  function covers(report: ReportMeta): string[] {
    const out = [report.inputs.period === "as_at" ? `As at ${toLabel.replace(" (latest)", "")}` : `${fromLabel.replace(" (earliest)", "")} – ${toLabel.replace(" (latest)", "")}`];
    if (report.inputs.breakdown) out.push(`by ${breakdownLabel}`);
    if (report.inputs.filters) out.push(filterCount ? `${plural(filterCount, "filter")} applied` : "all employees");
    if (report.inputs.names) out.push(masked ? "names masked" : "names shown");
    return out;
  }

  function ignores(report: ReportMeta): string | null {
    const unused = [
      filterCount && !report.inputs.filters ? "filters" : null,
      dateFrom && report.inputs.period === "as_at" ? "the From month" : null,
    ].filter(Boolean);
    return unused.length ? `Does not use ${unused.join(" or ")}.` : null;
  }

  const list = reports.data?.reports ?? [];
  const groups = Array.from(new Set(list.map((r) => r.group)));

  return (
    <div className="space-y-5">
      <PageHeader
        title="Report Centre"
        description="Standard Excel workbooks. Set the scope once; each report states what it covers. Every workbook opens with where its figures came from."
        actions={BUILDER_ROLES.has(activeRole ?? "") ? (
          <Button asChild variant="outline"><Link href="/reports/builder"><SlidersHorizontal size={14} /> Build a report</Link></Button>
        ) : null}
      />

      <div className="sr-only" role="status" aria-live="polite">{announce}</div>

      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside aria-labelledby="scope-heading" className="space-y-4 rounded-xl border border-ink-200 bg-white p-4 lg:sticky lg:top-20">
          <div>
            <h2 id="scope-heading" className="text-sm font-semibold text-ink-900">Report scope</h2>
            <p className="mt-0.5 text-xs text-ink-500">Applies to every report that reads it.</p>
          </div>

          <fieldset className="space-y-2">
            <legend className="text-xs font-medium text-ink-700">Period</legend>
            <div className="grid grid-cols-2 gap-2">
              <label className="text-xs text-ink-500">From
                <select className={cn(FIELD, "mt-1")} value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} disabled={!available.length}>
                  <option value="">Earliest</option>
                  {available.map((o) => <option key={o.period} value={o.period}>{o.label}</option>)}
                </select>
              </label>
              <label className="text-xs text-ink-500">To
                <select className={cn(FIELD, "mt-1")} value={dateTo} onChange={(e) => setDateTo(e.target.value)} disabled={!available.length}>
                  <option value="">Latest</option>
                  {available.map((o) => <option key={o.period} value={o.period}>{o.label}</option>)}
                </select>
              </label>
            </div>
            {reversed ? <p className="text-xs text-danger-700" role="alert">From is after To. Swap them to download a range report.</p> : null}
            <p className="text-xs text-ink-500">
              {earliest ? `Stored: ${earliest === latest ? earliest : `${earliest} – ${latest}`}. ` : ""}“As at” reports use the To month alone.
            </p>
          </fieldset>

          <label className="block text-xs font-medium text-ink-700">Break down by
            <select className={cn(FIELD, "mt-1")} value={groupBy} onChange={(e) => setGroupBy(e.target.value)}>
              {(dimensions.length ? dimensions : [{ key: "department", label: "Department" }]).map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}
            </select>
          </label>

          <div className="space-y-2">
            <FilterMenu align="left" dimensions={dimensions} filters={filters} onToggle={toggleFilter} onClear={() => setFilters({})} />
            <ActiveFilters dimensions={dimensions} filters={filters} onToggle={toggleFilter} onClear={() => setFilters({})} />
          </div>

          <fieldset>
            <legend className="text-xs font-medium text-ink-700">Employee names in workbooks</legend>
            <div className="mt-1.5 flex gap-4 text-[13px] text-ink-800">
              <label className="flex items-center gap-1.5"><input type="radio" name="names" className="accent-brand-600" checked={!masked} onChange={() => setMasked(false)} /> Show</label>
              <label className="flex items-center gap-1.5"><input type="radio" name="names" className="accent-brand-600" checked={masked} onChange={() => setMasked(true)} /> Mask</label>
            </div>
            <p className="mt-1 text-xs text-ink-500">Masking swaps names for initials and a stable token; figures are unchanged. Applies to reports that list employees.</p>
          </fieldset>
        </aside>

        <div className="min-w-0 space-y-6">
          {reports.isError ? (
            <AlertBanner variant="error" title="The report list could not be loaded" action={<Button size="sm" variant="outline" onClick={() => void reports.refetch()}>Try again</Button>}>
              {(reports.error as Error).message}
            </AlertBanner>
          ) : null}
          {!periods.isLoading && !periods.isError && available.length === 0 ? (
            <AlertBanner variant="warning" title="No salary register stored for this company">
              Register-based reports will contain no months — an empty workbook, not a zero payroll. <Link href="/payroll/upload" className="font-medium underline">Upload a register</Link>.
            </AlertBanner>
          ) : null}

          {reports.isLoading ? (
            <div className="space-y-3">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24 rounded-xl" />)}</div>
          ) : (
            groups.map((group) => (
              <section key={group} aria-labelledby={`g-${group}`}>
                <h2 id={`g-${group}`} className="mb-2 text-sm font-semibold text-ink-900">{group}</h2>
                <ul className="divide-y divide-ink-100 overflow-hidden rounded-xl border border-ink-200 bg-white">
                  {list.filter((r) => r.group === group).map((report) => {
                    const ex = exports[report.key];
                    const blocked = reversed && report.inputs.period === "range";
                    const note = ignores(report);
                    return (
                      <li key={report.key} className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-start">
                        <FileSpreadsheet size={18} className="mt-0.5 hidden flex-shrink-0 text-ink-500 sm:block" aria-hidden />
                        <div className="min-w-0 flex-1">
                          <h3 className="text-[14px] font-semibold text-ink-900">{report.title}</h3>
                          <p className="mt-0.5 text-[13px] text-ink-600">{report.description}</p>
                          <p className="mt-1.5 text-xs text-ink-500">
                            <span className="text-ink-700">{covers(report).join(" · ")}</span>
                            <span aria-hidden> · </span>Needs {report.required_data.toLowerCase()}
                            {note ? <span className="text-ink-500"> · {note}</span> : null}
                          </p>
                          {ex?.state === "done" ? (
                            <p className="mt-1.5 flex items-center gap-1.5 text-xs text-success-700">
                              <CheckCircle2 size={13} aria-hidden /> Downloaded {ex.filename} · {Math.max(1, Math.round(ex.bytes / 1024))} KB · {ex.at.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
                            </p>
                          ) : ex?.state === "failed" ? (
                            <p className="mt-1.5 flex items-start gap-1.5 text-xs text-danger-700">
                              <AlertCircle size={13} className="mt-px flex-shrink-0" aria-hidden /> Not generated: {ex.message}
                            </p>
                          ) : null}
                        </div>
                        <Button
                          size="sm"
                          variant="outline"
                          className="self-start"
                          disabled={ex?.state === "running" || blocked}
                          onClick={() => void download(report)}
                          aria-label={`${ex?.state === "failed" ? "Retry" : "Download"} ${report.title} (Excel)`}
                        >
                          {ex?.state === "running" ? <><Loader2 size={13} className="animate-spin" /> Generating…</>
                            : <><Download size={13} /> {ex?.state === "failed" ? "Retry" : ex?.state === "done" ? "Download again" : "Excel"}</>}
                        </Button>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ))
          )}

          <p className="text-xs text-ink-500">
            Workbooks are built from current stored data, not a signed snapshot: keep the file you download as the evidence.
            Nothing is cut short — a sheet longer than Excel allows continues on a second sheet. None of these is a statutory filing format.
          </p>
        </div>
      </div>
    </div>
  );
}
