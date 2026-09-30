"use client";

import { useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlertCircle, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Check, CheckCircle2, Copy, Download,
  FolderOpen, Loader2, Plus, RefreshCw, Save, X,
} from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { ActiveFilters, FilterMenu } from "@/components/cost/FilterMenu";
import { BackLink } from "@/components/layout/BackLink";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/drawer";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { apiDownload } from "@/lib/api";
import { fetchDimensions, fetchPeriods } from "@/lib/cost-analysis";
import { saveBlob } from "@/lib/download";
import { count, dateTime, inr, plural } from "@/lib/format";
import {
  CALC_METRICS, MAX_CALCULATIONS, MAX_RANGE_MONTHS, MONEY_FIELDS, PREVIEW_LIMIT, builderApi, monthsBetween,
  unknownMetrics, type BuilderField, type Preview, type SavedReport, type Spec,
} from "@/lib/report-builder";
import { useUnsavedChanges } from "@/lib/unsaved";
import { periodLabel } from "@/lib/workspace";
import { cn } from "@/lib/utils";

const FIELD = "h-9 w-full rounded-lg border border-ink-200 bg-white px-2.5 text-[13px] text-ink-900";
const WRITE_ROLES = new Set(["owner", "manager", "analyst"]);
const MANAGER_ROLES = new Set(["owner", "manager"]);
const STEPS = ["Dataset", "Columns", "Filters", "Calculations", "Grouping", "Layout", "Preview", "Save & export"] as const;

const INITIAL: Spec = {
  dataset: "payroll_cost", dimension: "department", fields: ["period", "dimension", "headcount", "gross", "ctc"],
  filters: {}, date_from: null, date_to: null, sort: "period", order: "asc", calculations: [],
};
type Meta = { name: string; description: string; visibility: "private" | "shared"; status: "draft" | "published" };
const NEW_META: Meta = { name: "Payroll cost by department", description: "", visibility: "private", status: "draft" };
type Export = { state: "running" } | { state: "done"; filename: string; bytes: number } | { state: "failed"; message: string };

/**
 * Build a management report from the approved payroll cost dataset.
 *
 * Eight steps, each reachable directly and each stating its own validity. A
 * preview shows at most 200 rows and says so beside the full count; an export
 * contains every row. A saved report is a definition, not a frozen result, and
 * every save is a new version.
 */
export default function ReportBuilderPage() {
  const { entity, activeRole } = useEntity();
  const qc = useQueryClient();
  const canUse = WRITE_ROLES.has(activeRole ?? "");
  const isManager = MANAGER_ROLES.has(activeRole ?? "");

  const datasets = useQuery({ queryKey: ["rb-datasets", entity?.id], queryFn: builderApi.datasets, enabled: !!entity && canUse });
  const saved = useQuery({ queryKey: ["rb-saved", entity?.id], queryFn: builderApi.saved, enabled: !!entity && canUse });
  const dims = useQuery({ queryKey: ["bi", "dimensions", entity?.id], queryFn: fetchDimensions, enabled: !!entity && canUse });
  const periods = useQuery({ queryKey: ["bi", "periods", entity?.id], queryFn: fetchPeriods, enabled: !!entity && canUse });

  const [step, setStep] = useState(0);
  const [visited, setVisited] = useState<Set<number>>(new Set([0]));
  const [spec, setSpec] = useState<Spec>(INITIAL);
  const [meta, setMeta] = useState<Meta>(NEW_META);
  const [active, setActive] = useState<SavedReport | null>(null);
  const [baseline, setBaseline] = useState(() => JSON.stringify({ spec: INITIAL, meta: NEW_META }));
  const [preview, setPreview] = useState<{ data: Preview; key: string } | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [exp, setExp] = useState<Export | null>(null);
  const [openSaved, setOpenSaved] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const previewSeq = useRef(0);

  const versions = useQuery({ queryKey: ["rb-versions", entity?.id, active?.id, active?.version], queryFn: () => builderApi.versions(active!.id), enabled: !!active });

  const specKey = JSON.stringify(spec);
  const dirty = JSON.stringify({ spec, meta }) !== baseline;
  useUnsavedChanges(dirty);

  const dataset = datasets.data?.datasets[0];
  const fields: (BuilderField & { calculated?: boolean })[] = useMemo(() => [
    ...(dataset?.fields ?? []),
    ...spec.calculations.map((c) => ({ key: c.key, label: c.label || "Untitled calculation", numeric: true, calculated: true })),
  ], [dataset, spec.calculations]);
  const labelOf = (key: string) => fields.find((f) => f.key === key)?.label ?? key;
  const available = periods.data?.periods ?? []; // newest first
  const dimensions = dims.data?.dimensions ?? [];
  const dimLabel = dataset?.dimensions.find((d) => d.key === spec.dimension)?.label ?? spec.dimension;

  // ── validity, per step ────────────────────────────────────────────────────
  const range = spec.date_from && spec.date_to ? monthsBetween(spec.date_from, spec.date_to) : null;
  const rangeError = range !== null && range < 1 ? "From is after To." : range !== null && range > MAX_RANGE_MONTHS ? `At most ${MAX_RANGE_MONTHS} months; this is ${range}.` : null;
  const calcErrors = spec.calculations.map((c) => {
    if (!c.label.trim()) return "Give it a column name.";
    if (!c.expression.trim()) return "Write an expression.";
    const unknown = unknownMetrics(c.expression);
    if (unknown.length) return `Not a metric: ${unknown.join(", ")}.`;
    if (!/^[\sA-Za-z0-9_+\-*/().]+$/.test(c.expression)) return "Use metric names, numbers, brackets and + − × ÷ only.";
    return null;
  });
  const stepError: (string | null)[] = [
    null,
    spec.fields.length ? null : "Choose at least one column.",
    rangeError,
    calcErrors.find(Boolean) ?? null,
    null,
    spec.fields.includes(spec.sort) ? null : "Sort by a column that is in the report.",
    null,
    meta.name.trim() ? null : "Name the report.",
  ];
  const valid = stepError.every((e) => !e);
  const monthLabel = (iso: string | null) => (iso ? periodLabel(iso) : null);
  const summary = [
    dataset?.label ?? "Payroll cost",
    plural(spec.fields.length, "column"),
    [spec.date_from || spec.date_to ? `${monthLabel(spec.date_from) ?? "Earliest"} – ${monthLabel(spec.date_to) ?? "latest"}` : "All months", Object.keys(spec.filters).length ? plural(Object.values(spec.filters).flat().length, "filter") : null].filter(Boolean).join(" · "),
    spec.calculations.length ? plural(spec.calculations.length, "calculation") : "None",
    `By ${dimLabel}`,
    `${labelOf(spec.sort)}, ${spec.order === "asc" ? "ascending" : "descending"}`,
    preview ? (preview.key === specKey ? "Up to date" : "Out of date") : "Not generated",
    active ? `v${active.version}${dirty ? " · unsaved changes" : ""}` : "Not saved",
  ];

  function go(n: number) {
    // Arriving at Preview shows current figures; earlier rows stay on screen while it refreshes.
    if (n === 6 && n !== step && valid && (!preview || preview.key !== specKey)) void runPreview();
    setStep(n);
    setVisited((v) => new Set(v).add(n));
    requestAnimationFrame(() => heading.current?.focus());
  }
  function update(next: Partial<Spec>) {
    setSpec((s) => ({ ...s, ...next }));
    setExp(null);
  }

  async function runPreview(target: Spec = spec) {
    const ticket = ++previewSeq.current; // only the latest request may land
    setPreviewing(true);
    setPreviewError(null);
    try {
      const data = await builderApi.preview(target);
      if (ticket === previewSeq.current) setPreview({ data, key: JSON.stringify(target) });
    } catch (e) {
      if (ticket === previewSeq.current) setPreviewError(e instanceof Error ? e.message : "The preview could not be generated.");
    } finally {
      if (ticket === previewSeq.current) setPreviewing(false);
    }
  }

  function adopt(report: SavedReport) {
    const m: Meta = { name: report.name, description: report.description ?? "", visibility: report.visibility, status: report.status };
    const s = { ...INITIAL, ...report.specification };
    setActive(report);
    setSpec(s);
    setMeta(m);
    setBaseline(JSON.stringify({ spec: s, meta: m }));
    setExp(null);
    setSaveError(null);
    return s;
  }

  function confirmDiscard() {
    return !dirty || window.confirm("You have unsaved changes. Discard them?");
  }

  function open(report: SavedReport) {
    if (!confirmDiscard()) return;
    const s = adopt(report);
    setOpenSaved(false);
    setVisited(new Set(STEPS.map((_, i) => i)));
    setStep(6);
    void runPreview(s);
  }

  function startNew() {
    if (!confirmDiscard()) return;
    setActive(null);
    setSpec(INITIAL);
    setMeta(NEW_META);
    setBaseline(JSON.stringify({ spec: INITIAL, meta: NEW_META }));
    setPreview(null);
    setExp(null);
    setVisited(new Set([0]));
    go(0);
  }

  async function copy(report: SavedReport) {
    if (!confirmDiscard()) return;
    try {
      const c = await builderApi.clone(report.id);
      await qc.invalidateQueries({ queryKey: ["rb-saved", entity?.id] });
      toast.success(`Copied as “${c.name}” — a private draft`);
      open(c);
    } catch (e) {
      toast.error("Not copied", { description: e instanceof Error ? e.message : "" });
    }
  }

  async function save() {
    setSaving(true);
    setSaveError(null);
    try {
      const result = await builderApi.save(active?.id ?? null, {
        name: meta.name.trim(), description: meta.description.trim() || null,
        specification: spec, visibility: meta.visibility, status: meta.status,
      });
      adopt(result);
      toast.success(`Saved as version ${result.version}`);
      await qc.invalidateQueries({ queryKey: ["rb-saved", entity?.id] });
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Not saved.");
    } finally {
      setSaving(false);
    }
  }

  async function download() {
    if (!active) return;
    setExp({ state: "running" });
    try {
      const { blob, filename, bytes } = await apiDownload(`/api/reports/builder/saved/${active.id}.xlsx`, `report-v${active.version}.xlsx`);
      saveBlob(blob, filename);
      setExp({ state: "done", filename, bytes });
    } catch (e) {
      setExp({ state: "failed", message: e instanceof Error ? e.message : "The workbook was not generated." });
    }
  }

  if (!canUse) {
    return (
      <div className="space-y-4">
        <BackLink fallback="/reports">Report Centre</BackLink>
        <PageHeader title="Report Builder" />
        <EmptyState
          title="Report Builder needs analyst access"
          description="Your role in this company can download the standard reports but not build new ones. An owner or manager can change your role."
          action={<Button asChild variant="outline"><Link href="/reports">Go to the Report Centre</Link></Button>}
        />
      </div>
    );
  }

  const loadError = datasets.error || saved.error;
  const stale = !!preview && preview.key !== specKey;
  const exportBlocker = !active ? "Save the report to export it."
    : dirty ? `You have unsaved changes. Save them first — an export always uses a saved version, so the file matches a definition someone can reopen.`
    : !spec.date_from || !spec.date_to ? "Choose both a From and a To month in Filters. An export names the months it covers."
    : null;

  return (
    <div className="space-y-5">
      <BackLink fallback="/reports">Report Centre</BackLink>
      <PageHeader
        title={active ? meta.name || active.name : "New report"}
        description="Payroll cost at one row per payroll month and breakdown value, from the same calculation as Cost analysis."
        meta={
          <>
            {active ? <StatusPill tone={active.status === "published" ? "success" : "neutral"}>Version {active.version} · {active.status === "published" ? "Published" : "Draft"}</StatusPill> : <StatusPill tone="neutral">Not saved yet</StatusPill>}
            {active ? <span>{active.visibility === "shared" ? "Shared with this company" : "Private to you"}</span> : null}
            {dirty && active ? <StatusPill tone="warning">Unsaved changes</StatusPill> : null}
          </>
        }
        actions={
          <>
            <Button variant="ghost" onClick={startNew}><Plus size={14} /> New</Button>
            <Button variant="outline" onClick={() => setOpenSaved(true)}>
              <FolderOpen size={14} /> Saved reports{saved.data ? ` (${saved.data.reports.length})` : ""}
            </Button>
          </>
        }
      />

      {loadError ? (
        <AlertBanner variant="error" title="Report Builder could not load" action={<Button size="sm" variant="outline" onClick={() => { void datasets.refetch(); void saved.refetch(); }}>Try again</Button>}>
          {(loadError as Error).message}
        </AlertBanner>
      ) : null}

      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[232px_minmax(0,1fr)]">
        <nav aria-label="Report steps" className="min-w-0 lg:sticky lg:top-20">
          <ol className="flex gap-1 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:pb-0">
            {STEPS.map((label, i) => {
              const err = visited.has(i) ? stepError[i] : null;
              const settled = i === 6 ? !!preview && preview.key === specKey : i === 7 ? !!active && !dirty : true;
              const done = visited.has(i) && !err && i !== step && settled;
              return (
                <li key={label} className="flex-shrink-0">
                  <button
                    type="button"
                    onClick={() => go(i)}
                    aria-current={i === step ? "step" : undefined}
                    className={cn(
                      "flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors duration-fast",
                      i === step ? "bg-brand-50 ring-1 ring-brand-200" : "hover:bg-ink-50",
                    )}
                  >
                    <span aria-hidden className={cn(
                      "mt-px flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-[11px] font-semibold",
                      err ? "bg-danger-600 text-white" : i === step ? "bg-brand-600 text-white" : done ? "bg-success-600 text-white" : "border border-ink-200 bg-white text-ink-500",
                    )}>
                      {err ? <X size={11} strokeWidth={3} /> : done ? <Check size={11} strokeWidth={3} /> : i + 1}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[13px] font-medium text-ink-900">
                        {label}
                        <span className="sr-only">{err ? ` — needs attention: ${err}` : done ? " — complete" : ""}</span>
                      </span>
                      <span className={cn("hidden truncate text-xs lg:block", err ? "text-danger-700" : "text-ink-500")}>{err ?? summary[i]}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </nav>

        <section aria-labelledby="step-heading" className="min-w-0 rounded-xl border border-ink-200 bg-white">
          <div className="border-b border-ink-100 px-5 py-4">
            <p className="text-xs text-ink-500">Step {step + 1} of {STEPS.length}</p>
            <h2 id="step-heading" ref={heading} tabIndex={-1} className="text-base font-semibold text-ink-900 focus:outline-none">{STEPS[step]}</h2>
          </div>

          <div className="space-y-4 px-5 py-5">
            {!dataset && !loadError ? (
              <div className="space-y-2"><Skeleton className="h-5 w-64" /><Skeleton className="h-20 w-full" /></div>
            ) : null}

            {dataset && step === 0 ? (
              <div className="space-y-3">
                <label className="flex cursor-default items-start gap-3 rounded-xl border border-brand-300 bg-brand-50/40 p-4">
                  <input type="radio" checked readOnly className="mt-1 accent-brand-600" name="dataset" />
                  <span>
                    <span className="block text-[14px] font-semibold text-ink-900">{dataset.label}</span>
                    <span className="mt-0.5 block text-[13px] text-ink-600">One row is {dataset.grain.toLowerCase()}. {dataset.note}</span>
                  </span>
                </label>
                <p className="text-xs text-ink-500">
                  This is the one dataset the builder offers. For one row per employee, use <Link href="/reports" className="font-medium text-brand-700 underline">Employee payroll cost</Link> in the Report Centre.
                </p>
              </div>
            ) : null}

            {dataset && step === 1 ? (
              <div className="grid gap-5 md:grid-cols-2">
                <div>
                  <h3 className="text-xs font-medium text-ink-700">In the report, in column order</h3>
                  {spec.fields.length ? (
                    <ol className="mt-2 divide-y divide-ink-100 rounded-lg border border-ink-200">
                      {spec.fields.map((key, i) => (
                        <li key={key} className="flex items-center gap-2 px-3 py-1.5 text-[13px]">
                          <span className="w-5 text-xs tabular-nums text-ink-500">{i + 1}</span>
                          <span className="min-w-0 flex-1 truncate text-ink-900">{labelOf(key)}</span>
                          <IconBtn label={`Move ${labelOf(key)} earlier`} disabled={i === 0} onClick={() => { const f = spec.fields.slice(); [f[i - 1], f[i]] = [f[i], f[i - 1]]; update({ fields: f }); }}><ArrowUp size={13} /></IconBtn>
                          <IconBtn label={`Move ${labelOf(key)} later`} disabled={i === spec.fields.length - 1} onClick={() => { const f = spec.fields.slice(); [f[i + 1], f[i]] = [f[i], f[i + 1]]; update({ fields: f }); }}><ArrowDown size={13} /></IconBtn>
                          <IconBtn label={`Remove ${labelOf(key)}`} disabled={spec.fields.length === 1} onClick={() => { const f = spec.fields.filter((x) => x !== key); update({ fields: f, sort: f.includes(spec.sort) ? spec.sort : f[0] }); }}><X size={13} /></IconBtn>
                        </li>
                      ))}
                    </ol>
                  ) : null}
                  <p className="mt-2 text-xs text-ink-500">A report keeps at least one column. Employee names are not in this dataset.</p>
                </div>
                <div>
                  <h3 className="text-xs font-medium text-ink-700">Available</h3>
                  <ul className="mt-2 flex flex-wrap gap-1.5">
                    {fields.filter((f) => !spec.fields.includes(f.key)).map((f) => (
                      <li key={f.key}>
                        <button type="button" onClick={() => update({ fields: [...spec.fields, f.key] })}
                          className="inline-flex h-8 items-center gap-1 rounded-full border border-ink-200 bg-white px-3 text-[13px] text-ink-800 hover:border-brand-300 hover:bg-brand-50">
                          <Plus size={12} aria-hidden /> {f.label}{f.calculated ? <span className="text-xs text-ink-500"> · calculated</span> : null}
                        </button>
                      </li>
                    ))}
                    {fields.every((f) => spec.fields.includes(f.key)) ? <li className="text-xs text-ink-500">Every column is in the report.</li> : null}
                  </ul>
                </div>
              </div>
            ) : null}

            {dataset && step === 2 ? (
              <div className="space-y-5">
                <fieldset>
                  <legend className="text-xs font-medium text-ink-700">Payroll months</legend>
                  <div className="mt-1 grid max-w-md grid-cols-2 gap-3">
                    {(["date_from", "date_to"] as const).map((k) => (
                      <label key={k} className="text-xs text-ink-500">{k === "date_from" ? "From" : "To"}
                        <select className={cn(FIELD, "mt-1")} value={spec[k] ?? ""} onChange={(e) => update({ [k]: e.target.value || null })} aria-invalid={!!rangeError}>
                          <option value="">{k === "date_from" ? "Earliest stored" : "Latest stored"}</option>
                          {available.map((p) => <option key={p.period} value={p.period}>{p.label}</option>)}
                        </select>
                      </label>
                    ))}
                  </div>
                  {rangeError ? <p className="mt-1.5 text-xs text-danger-700">{rangeError}</p> : null}
                  <p className="mt-1.5 text-xs text-ink-500">
                    {range ? `${plural(range, "month")}. ` : ""}Up to {MAX_RANGE_MONTHS} months. An Excel export needs both months set.
                    {!available.length && !periods.isLoading ? " No salary register is stored for this company yet." : ""}
                  </p>
                </fieldset>
                <div className="space-y-2">
                  <div className="max-w-xs"><FilterMenu align="left" dimensions={dimensions} filters={spec.filters} onClear={() => update({ filters: {} })}
                    onToggle={(key, value) => {
                      const cur = spec.filters[key] ?? [];
                      const next = cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value];
                      const out = { ...spec.filters, [key]: next };
                      if (!next.length) delete out[key];
                      update({ filters: out });
                    }} /></div>
                  <ActiveFilters dimensions={dimensions} filters={spec.filters} onClear={() => update({ filters: {} })}
                    onToggle={(key, value) => {
                      const next = (spec.filters[key] ?? []).filter((v) => v !== value);
                      const out = { ...spec.filters, [key]: next };
                      if (!next.length) delete out[key];
                      update({ filters: out });
                    }} />
                  <p className="text-xs text-ink-500">Values within one dimension are alternatives; different dimensions narrow each other.</p>
                </div>
              </div>
            ) : null}

            {dataset && step === 3 ? (
              <div className="space-y-4">
                <p className="text-[13px] text-ink-600">Optional. A calculated column combines metrics with + − × ÷ and brackets, per row. Division by zero leaves the cell blank, never zero.</p>
                {spec.calculations.map((c, i) => {
                  const setCalc = (patch: Partial<typeof c>) => update({ calculations: spec.calculations.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
                  return (
                    <div key={c.key} className="space-y-2 rounded-lg border border-ink-200 p-3">
                      <div className="grid gap-3 sm:grid-cols-[1fr_2fr_auto] sm:items-end">
                        <label className="text-xs font-medium text-ink-700">Column name<input className={cn(FIELD, "mt-1")} value={c.label} maxLength={80} onChange={(e) => setCalc({ label: e.target.value })} /></label>
                        <label className="text-xs font-medium text-ink-700">Expression<input className={cn(FIELD, "mt-1 font-mono")} value={c.expression} maxLength={160} placeholder="ctc / headcount" aria-invalid={!!calcErrors[i]} onChange={(e) => setCalc({ expression: e.target.value })} /></label>
                        <Button variant="ghost" size="sm" onClick={() => {
                          const f = spec.fields.filter((x) => x !== c.key);
                          update({ calculations: spec.calculations.filter((_, j) => j !== i), fields: f.length ? f : ["period"], sort: spec.sort === c.key ? (f[0] ?? "period") : spec.sort });
                        }}>Remove</Button>
                      </div>
                      <div className="flex flex-wrap items-center gap-1.5 text-xs text-ink-500">
                        Insert:
                        {CALC_METRICS.map((m) => (
                          <button key={m} type="button" className="rounded border border-ink-200 px-1.5 py-0.5 font-mono text-[11px] text-ink-700 hover:bg-ink-50"
                            onClick={() => setCalc({ expression: `${c.expression}${c.expression && !/[\s(+\-*/]$/.test(c.expression) ? " " : ""}${m}` })}>{m}</button>
                        ))}
                      </div>
                      {calcErrors[i] ? <p className="text-xs text-danger-700">{calcErrors[i]}</p> : null}
                    </div>
                  );
                })}
                {spec.calculations.length < MAX_CALCULATIONS ? (
                  <Button variant="outline" size="sm" onClick={() => {
                    const n = [1, 2, 3, 4].find((k) => !spec.calculations.some((c) => c.key === `calc_${k}`)) ?? 9;
                    const key = `calc_${n}`;
                    update({ calculations: [...spec.calculations, { key, label: "", expression: "" }], fields: [...spec.fields, key] });
                  }}><Plus size={13} /> Add a calculated column</Button>
                ) : <p className="text-xs text-ink-500">Three calculated columns is the most a report can hold.</p>}
                {spec.calculations.length ? <p className="text-xs text-ink-500">A new calculation is added to the end of the columns; reorder it under Columns.</p> : null}
              </div>
            ) : null}

            {dataset && step === 4 ? (
              <fieldset>
                <legend className="text-[13px] text-ink-600">One row per payroll month and value of:</legend>
                <div className="mt-2 grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
                  {dataset.dimensions.map((d) => (
                    <label key={d.key} className={cn("flex items-center gap-2 rounded-lg border px-3 py-2 text-[13px]", spec.dimension === d.key ? "border-brand-300 bg-brand-50/50 text-ink-900" : "border-ink-200 text-ink-700 hover:bg-ink-50")}>
                      <input type="radio" name="dimension" className="accent-brand-600" checked={spec.dimension === d.key} onChange={() => update({ dimension: d.key })} /> {d.label}
                    </label>
                  ))}
                </div>
                <p className="mt-2 text-xs text-ink-500">Employees with no value appear as Unassigned rather than disappearing. A month with no one paid in a group has no row — a gap, not a zero.</p>
              </fieldset>
            ) : null}

            {dataset && step === 5 ? (
              <div className="space-y-4">
                <div className="grid max-w-lg gap-3 sm:grid-cols-2">
                  <label className="text-xs font-medium text-ink-700">Sort by
                    <select className={cn(FIELD, "mt-1")} value={spec.sort} onChange={(e) => update({ sort: e.target.value })}>
                      {spec.fields.map((k) => <option key={k} value={k}>{labelOf(k)}</option>)}
                    </select>
                  </label>
                  <fieldset>
                    <legend className="text-xs font-medium text-ink-700">Order</legend>
                    <div className="mt-2.5 flex gap-4 text-[13px]">
                      {(["asc", "desc"] as const).map((o) => (
                        <label key={o} className="flex items-center gap-1.5"><input type="radio" name="order" className="accent-brand-600" checked={spec.order === o} onChange={() => update({ order: o })} /> {o === "asc" ? "Ascending" : "Descending"}</label>
                      ))}
                    </div>
                  </fieldset>
                </div>
                <p className="text-xs text-ink-500">Layout is a table: the columns you chose, one row per month and group. Pivot, chart and PDF layouts are not available in the builder.</p>
              </div>
            ) : null}

            {dataset && step === 6 ? (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-3">
                  <Button onClick={() => void runPreview()} disabled={previewing || !valid}>
                    {previewing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} {preview ? "Refresh preview" : "Generate preview"}
                  </Button>
                  {!valid ? <span className="text-xs text-danger-700">Fix the steps marked in red first.</span> : null}
                  {stale && !previewing ? <StatusPill tone="warning">Out of date — the definition changed since this preview</StatusPill> : null}
                </div>
                {previewError ? <AlertBanner variant="error" title="The preview was not generated">{previewError}</AlertBanner> : null}
                {preview ? <PreviewResult preview={preview.data} spec={spec} labelOf={labelOf} dimLabel={dimLabel} busy={previewing} stale={stale} /> : !previewing ? (
                  <p className="text-[13px] text-ink-500">Nothing generated yet. A preview reads current data and changes nothing.</p>
                ) : <Skeleton className="h-40 w-full" />}
              </div>
            ) : null}

            {dataset && step === 7 ? (
              <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_300px]">
                <div className="space-y-4">
                  <label className="block text-xs font-medium text-ink-700">Report name
                    <input className={cn(FIELD, "mt-1")} value={meta.name} maxLength={120} aria-invalid={!meta.name.trim()} onChange={(e) => setMeta({ ...meta, name: e.target.value })} />
                  </label>
                  <label className="block text-xs font-medium text-ink-700">Description <span className="font-normal text-ink-500">(optional)</span>
                    <textarea className="mt-1 block min-h-[64px] w-full rounded-lg border border-ink-200 bg-white px-2.5 py-2 text-[13px] text-ink-900" maxLength={1000} value={meta.description} onChange={(e) => setMeta({ ...meta, description: e.target.value })} />
                  </label>
                  <fieldset>
                    <legend className="text-xs font-medium text-ink-700">Who can open it</legend>
                    <div className="mt-1.5 space-y-1 text-[13px]">
                      <label className="flex items-center gap-1.5"><input type="radio" name="vis" className="accent-brand-600" checked={meta.visibility === "private"} onChange={() => setMeta({ ...meta, visibility: "private" })} /> Only me</label>
                      <label className={cn("flex items-center gap-1.5", !isManager && "text-ink-500")}><input type="radio" name="vis" className="accent-brand-600" disabled={!isManager} checked={meta.visibility === "shared"} onChange={() => setMeta({ ...meta, visibility: "shared" })} /> Analysts and above in this company</label>
                    </div>
                  </fieldset>
                  <fieldset>
                    <legend className="text-xs font-medium text-ink-700">Status</legend>
                    <div className="mt-1.5 space-y-1 text-[13px]">
                      <label className="flex items-center gap-1.5"><input type="radio" name="status" className="accent-brand-600" checked={meta.status === "draft"} onChange={() => setMeta({ ...meta, status: "draft" })} /> Draft</label>
                      <label className={cn("flex items-center gap-1.5", !isManager && "text-ink-500")}><input type="radio" name="status" className="accent-brand-600" disabled={!isManager} checked={meta.status === "published"} onChange={() => setMeta({ ...meta, status: "published" })} /> Published — only a manager can change it afterwards</label>
                    </div>
                  </fieldset>
                  {!isManager ? <p className="text-xs text-ink-500">Sharing and publishing need a manager or owner.</p> : null}
                  {saveError ? <AlertBanner variant="error" title="Not saved">{saveError}</AlertBanner> : null}
                  <div className="flex flex-wrap items-center gap-3">
                    <Button onClick={() => void save()} disabled={saving || !valid || !dirty}>
                      {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} {active ? `Save as version ${active.version + 1}` : "Save report"}
                    </Button>
                    <span className="text-xs text-ink-500">{!valid ? "Fix the steps marked in red first." : !dirty ? "No changes since the last save." : "Saving stores the choices, not the figures; each save is a new version."}</span>
                  </div>
                </div>

                <aside className="space-y-4">
                  <div className="rounded-lg border border-ink-200 p-3.5">
                    <h3 className="text-[13px] font-semibold text-ink-900">Excel export</h3>
                    <p className="mt-1 text-xs text-ink-500">Every matched row — the preview&apos;s {PREVIEW_LIMIT}-row limit does not apply — with About, Summary, Details and Data basis sheets.</p>
                    {exportBlocker ? <p className="mt-2 text-xs text-ink-700">{exportBlocker}</p> : null}
                    <Button className="mt-3" variant="outline" size="sm" disabled={!!exportBlocker || exp?.state === "running"} onClick={() => void download()}>
                      {exp?.state === "running" ? <><Loader2 size={13} className="animate-spin" /> Generating…</> : <><Download size={13} /> {exp?.state === "failed" ? "Retry download" : exp?.state === "done" ? "Download again" : `Download version ${active?.version ?? ""}`.trim()}</>}
                    </Button>
                    <div role="status" aria-live="polite" className="mt-2 text-xs">
                      {exp?.state === "done" ? <span className="flex items-center gap-1.5 text-success-700"><CheckCircle2 size={13} aria-hidden /> Downloaded {exp.filename} · {Math.max(1, Math.round(exp.bytes / 1024))} KB</span> : null}
                      {exp?.state === "failed" ? <span className="flex items-start gap-1.5 text-danger-700"><AlertCircle size={13} className="mt-px flex-shrink-0" aria-hidden /> Not generated: {exp.message}</span> : null}
                    </div>
                  </div>

                  {active ? (
                    <div className="rounded-lg border border-ink-200 p-3.5">
                      <h3 className="text-[13px] font-semibold text-ink-900">Versions</h3>
                      {versions.isLoading ? <Skeleton className="mt-2 h-12 w-full" /> : (
                        <ol className="mt-2 space-y-1.5">
                          {(versions.data?.versions ?? []).map((v) => (
                            <li key={v.version} className="flex items-center justify-between gap-2 text-xs">
                              <span className="min-w-0">
                                <span className="font-medium text-ink-800">v{v.version}</span>{v.version === active.version ? <span className="text-ink-500"> · current</span> : null}
                                <span className="block truncate text-ink-500">{v.name} · {dateTime(v.created_at)}</span>
                              </span>
                              {v.version !== active.version ? (
                                <button type="button" className="flex-shrink-0 font-medium text-brand-700 hover:underline" onClick={() => {
                                  update({ ...INITIAL, ...v.specification });
                                  setMeta((m) => ({ ...m, name: v.name }));
                                  toast.message(`Version ${v.version} loaded into the editor`, { description: `Save to make it version ${active.version + 1}.` });
                                }}>Load</button>
                              ) : null}
                            </li>
                          ))}
                        </ol>
                      )}
                    </div>
                  ) : null}
                </aside>
              </div>
            ) : null}
          </div>

          <div className="flex items-center justify-between border-t border-ink-100 px-5 py-3">
            <Button variant="ghost" disabled={step === 0} onClick={() => go(step - 1)}><ArrowLeft size={14} /> {step > 0 ? STEPS[step - 1] : "Back"}</Button>
            {step < STEPS.length - 1 ? (
              <Button variant="outline" onClick={() => go(step + 1)}>
                {STEPS[step + 1]} <ArrowRight size={14} />
              </Button>
            ) : null}
          </div>
        </section>
      </div>

      <Drawer open={openSaved} onClose={() => setOpenSaved(false)} title="Saved reports" description="Your private drafts and reports shared with this company.">
        {saved.isLoading ? <Skeleton className="h-24 w-full" /> : (saved.data?.reports.length ?? 0) === 0 ? (
          <p className="text-[13px] text-ink-500">No saved reports yet. Build one and save it at the last step.</p>
        ) : (
          <ul className="divide-y divide-ink-100">
            {saved.data!.reports.map((r) => (
              <li key={r.id} className="py-3">
                <p className="text-[13px] font-medium text-ink-900">{r.name}{active?.id === r.id ? <span className="font-normal text-ink-500"> · open</span> : null}</p>
                <p className="text-xs text-ink-500">v{r.version} · {r.status === "published" ? "Published" : "Draft"} · {r.visibility === "shared" ? "Shared" : "Private"} · {dateTime(r.updated_at)}</p>
                <div className="mt-1.5 flex gap-2">
                  <Button size="sm" variant="outline" onClick={() => open(r)}>Open</Button>
                  <Button size="sm" variant="ghost" onClick={() => void copy(r)}><Copy size={13} /> Copy</Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Drawer>
    </div>
  );
}

function IconBtn({ label, disabled, onClick, children }: { label: string; disabled?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" aria-label={label} title={label} disabled={disabled} onClick={onClick}
      className="inline-flex h-7 w-7 items-center justify-center rounded-md text-ink-500 hover:bg-ink-100 hover:text-ink-900 disabled:opacity-30 disabled:hover:bg-transparent">
      {children}
    </button>
  );
}

const TOTALS: [string, string][] = [["ctc", "Total CTC"], ["gross", "Gross pay"], ["net", "Net pay"], ["employer_cost", "Employer contributions"], ["headcount", "People paid"]];

function PreviewResult({ preview, spec, labelOf, dimLabel, busy, stale }: {
  preview: Preview; spec: Spec; labelOf: (k: string) => string; dimLabel: string; busy: boolean; stale: boolean;
}) {
  if (preview.status === "missing_data") {
    return <EmptyState title="No salary register in this range" description="There is nothing to report on for these months — not a zero payroll. Upload the register, or widen the months under Filters." />;
  }
  if (preview.status === "no_matching_records") {
    return <EmptyState title="No rows match" description="Registers exist for these months, but no one paid matches the filters. Loosen them under Filters." />;
  }
  const shown = preview.rows.length;
  const fmt = (key: string, v: string | number | null) => {
    if (v === null || v === undefined) return <span className="text-ink-500" title="Not available">—</span>;
    if (key === "period") return periodLabel(String(v));
    if (MONEY_FIELDS.has(key)) return inr(Number(v));
    if (key === "headcount" || key === "person_months") return count(Number(v));
    if (typeof v === "number") return v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
    return v;
  };
  return (
    <div className={cn("space-y-3 transition-opacity duration-fast", (busy || stale) && "opacity-60")} aria-busy={busy}>
      <p className="text-[13px] text-ink-800" role="status">
        <b>{count(preview.record_count)} rows</b> matched.{" "}
        {preview.truncated_preview
          ? <span className="text-warning-800">Showing the first {count(shown)}. The Excel export contains all {count(preview.record_count)}.</span>
          : <span className="text-ink-500">Showing all of them.</span>}
      </p>
      {preview.control_totals ? (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-lg bg-ink-50 px-3 py-2.5 sm:grid-cols-5">
          {TOTALS.map(([k, l]) => (
            <div key={k}>
              <dt className="text-[11px] text-ink-500">{l}</dt>
              <dd className="text-[13px] font-semibold tabular-nums text-ink-900">{k === "headcount" ? count(preview.control_totals![k]) : inr(preview.control_totals![k])}</dd>
            </div>
          ))}
          <p className="col-span-full text-[11px] text-ink-500">Control totals for the whole range and filters, before the breakdown — they should match Cost analysis for the same scope.</p>
        </dl>
      ) : null}
      <Table containerClassName="max-h-[480px] rounded-lg border border-ink-200">
        <TableHeader>
          <TableRow>
            {spec.fields.map((k, i) => {
              const numeric = !["period", "dimension"].includes(k);
              return <TableHead key={k} numeric={numeric} pin={i === 0}>{k === "dimension" ? dimLabel : labelOf(k)}</TableHead>;
            })}
          </TableRow>
        </TableHeader>
        <TableBody>
          {preview.rows.map((row, r) => (
            <TableRow key={r}>
              {spec.fields.map((k, i) => <TableCell key={k} numeric={!["period", "dimension"].includes(k)} pin={i === 0}>{fmt(k, row[k])}</TableCell>)}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
