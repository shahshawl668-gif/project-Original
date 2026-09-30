"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Check, CircleDashed, Download, FileSpreadsheet, History, Loader2, Search, ShieldCheck, UploadCloud, X } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Stepper, type StepState } from "@/components/ui/stepper";
import { useEntity } from "@/context/EntityContext";
import { apiFetch, getActiveEntityId, parseEnvelopeResponse } from "@/lib/api";
import { saveBlob } from "@/lib/download";
import { count, plural } from "@/lib/format";
import { cn } from "@/lib/utils";
import { monthLabel, validationApi, type RegisterUpload, type ValidationJob } from "@/lib/validation";
import { normalisePeriod, useWorkingPeriod } from "@/lib/workspace";

type PreviewRow = Record<string, unknown>;
type ImportProfile = { id: string; name: string; column_mapping: Record<string, string> };
type Preview = {
  columns: string[];
  preview: PreviewRow[];
  mapping: Record<string, string>;
  match?: Record<string, "exact" | "alias">;
  destinations: string[];
  required?: string[];
  components?: string[];
  employee_count: number;
};
type Checked = {
  columns: string[];
  preview: PreviewRow[];
  missing_required: string[];
  warnings: string[];
  employee_count: number;
  upload: RegisterUpload;
};
type Origin = "exact" | "alias" | "profile" | "manual";
type Phase = "choose" | "parsing" | "map" | "checking" | "checked" | "queueing";

const ORIGIN_LABEL: Record<Origin, string> = {
  exact: "Same name",
  alias: "Known alias",
  profile: "Saved format",
  manual: "Set by you",
};

const RUN_TYPES = [
  { id: "regular", label: "Regular", desc: "The month's payroll. Becomes the month's register for cost and dashboards." },
  { id: "arrear", label: "Arrear", desc: "A past-period correction. Validated, but does not replace the month's register." },
  { id: "increment_arrear", label: "Increment + arrear", desc: "Arrears from a CTC change. Validated, not added to the register." },
] as const;

const human = (field: string) => field.replaceAll("_", " ");

/**
 * Bringing a salary register in, in four visible stages: choose the file,
 * map its columns, have the server check it, then queue validation. Each
 * stage says what happened; nothing is described as done before the server
 * has confirmed it.
 */
export default function UploadPage() {
  const router = useRouter();
  const { entity, activeRole } = useEntity();
  const working = useWorkingPeriod();
  const [phase, setPhase] = useState<Phase>("choose");
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [strict, setStrict] = useState(true);
  const [runType, setRunType] = useState<(typeof RUN_TYPES)[number]["id"]>("regular");
  const [periodMonth, setPeriodMonth] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [origin, setOrigin] = useState<Record<string, Origin>>({});
  const [profiles, setProfiles] = useState<ImportProfile[]>([]);
  const [profileName, setProfileName] = useState("");
  const [query, setQuery] = useState("");
  const [show, setShow] = useState<"all" | "unmapped" | "mapped">("all");
  const [checked, setChecked] = useState<Checked | null>(null);
  const [error, setError] = useState<{ stage: Phase; message: string } | null>(null);
  const [activeJobs, setActiveJobs] = useState<ValidationJob[]>([]);
  const [components, setComponents] = useState<string[] | null>(null);
  const prefilled = useRef(false);
  const canWrite = activeRole !== "viewer";

  // The month defaults to the working period only when someone chose it.
  useEffect(() => {
    if (!prefilled.current && working.source === "chosen" && working.period) {
      setPeriodMonth(working.period);
      prefilled.current = true;
    }
  }, [working.period, working.source]);

  useEffect(() => {
    if (!entity?.id) return;
    let cancelled = false;
    void apiFetch("/api/payroll/import-profiles").then(parseEnvelopeResponse<ImportProfile[]>)
      .then((data) => { if (!cancelled) setProfiles(data); })
      .catch(() => { if (!cancelled) setProfiles([]); });
    void apiFetch("/api/components").then(parseEnvelopeResponse<{ component_name: string }[]>)
      .then((rows) => { if (!cancelled) setComponents(rows.map((r) => r.component_name)); })
      .catch(() => { if (!cancelled) setComponents(null); });
    // A validation someone started and walked away from is still running.
    void validationApi.jobs({ active: true })
      .then((jobs) => { if (!cancelled) setActiveJobs(jobs); })
      .catch(() => { if (!cancelled) setActiveJobs([]); });
    return () => { cancelled = true; };
  }, [entity?.id]);

  const reset = (f: File | null) => {
    setFile(f);
    setPreview(null);
    setMapping({});
    setOrigin({});
    setChecked(null);
    setError(null);
    setQuery("");
    setPhase("choose");
  };

  const parse = async () => {
    if (!file) return;
    const requestEntityId = getActiveEntityId();
    setPhase("parsing");
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const data = await parseEnvelopeResponse<Preview>(await apiFetch("/api/payroll/preview", { method: "POST", body: fd }));
      if (getActiveEntityId() !== requestEntityId) return;
      setPreview(data);
      setMapping(data.mapping);
      setOrigin(Object.fromEntries(Object.keys(data.mapping).map((s) => [s, data.match?.[s] ?? "exact"])));
      setPhase("map");
      requestAnimationFrame(() => document.getElementById("s2")?.scrollIntoView({ behavior: "smooth", block: "start" }));
    } catch (err) {
      if (getActiveEntityId() !== requestEntityId) return;
      setError({ stage: "parsing", message: err instanceof Error ? err.message : "The file could not be read." });
      setPhase("choose");
    }
  };

  const applyProfile = (name: string) => {
    setProfileName(name);
    const profile = profiles.find((p) => p.name === name);
    if (!profile || !preview) return;
    const next = Object.fromEntries(
      Object.entries(profile.column_mapping).filter(([s, d]) => preview.columns.includes(s) && preview.destinations.includes(d)),
    );
    setMapping(next);
    setOrigin(Object.fromEntries(Object.keys(next).map((s) => [s, "profile" as Origin])));
  };

  const setDestination = (source: string, destination: string) => {
    setMapping((old) => {
      const next = { ...old };
      if (destination) next[source] = destination;
      else delete next[source];
      return next;
    });
    setOrigin((old) => ({ ...old, [source]: "manual" }));
  };

  const required = useMemo(() => {
    const all = preview?.required ?? ["employee_id"];
    return strict ? all : ["employee_id"];
  }, [preview?.required, strict]);
  const mappedTo = useMemo(() => {
    const out: Record<string, string> = {};
    for (const [s, d] of Object.entries(mapping)) out[d] = s;
    return out;
  }, [mapping]);
  const unmappedRequired = required.filter((r) => !mappedTo[r]);
  const monthNeeded = !periodMonth;

  const check = async () => {
    if (!file || !preview) return;
    const requestEntityId = getActiveEntityId();
    setPhase("checking");
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("meta", JSON.stringify({
        run_type: runType,
        period_month: periodMonth ? `${periodMonth}-01` : null,
        effective_month_from: from || null,
        effective_month_to: to || null,
        strict_header_check: strict,
        column_mapping: mapping,
        // The register is validated on the server from the stored upload, so
        // there is no reason to ship every row back to this page.
        return_employees: false,
      }));
      const data = await parseEnvelopeResponse<Checked>(await apiFetch("/api/payroll/upload", { method: "POST", body: fd }));
      if (getActiveEntityId() !== requestEntityId) return;
      setChecked(data);
      setPhase("checked");
      requestAnimationFrame(() => document.getElementById("s3")?.scrollIntoView({ behavior: "smooth", block: "start" }));
      if (profileName.trim()) {
        try {
          await parseEnvelopeResponse(await apiFetch("/api/payroll/import-profiles", {
            method: "POST", body: JSON.stringify({ name: profileName.trim(), column_mapping: mapping }),
          }));
          const formats = await parseEnvelopeResponse<ImportProfile[]>(await apiFetch("/api/payroll/import-profiles"));
          if (getActiveEntityId() === requestEntityId) setProfiles(formats);
          toast.success(`Format “${profileName.trim()}” saved for next month`);
        } catch (err) {
          toast.error("The register was checked, but the format was not saved", {
            description: err instanceof Error ? err.message : "Try saving the format again later.",
          });
        }
      }
    } catch (err) {
      if (getActiveEntityId() !== requestEntityId) return;
      setError({ stage: "checking", message: err instanceof Error ? err.message : "The register could not be checked." });
      setPhase("map");
    }
  };

  const validate = async () => {
    const upload = checked?.upload;
    if (!upload?.period_month) {
      setError({ stage: "queueing", message: "Choose the payroll month and check the register again — validation is recorded against a month." });
      return;
    }
    const requestEntityId = getActiveEntityId();
    setPhase("queueing");
    setError(null);
    try {
      const { job, already_queued } = await validationApi.enqueue({
        period_month: upload.period_month,
        upload_id: upload.id,
        run_type: runType,
        effective_month_from: from || null,
        effective_month_to: to || null,
      });
      if (getActiveEntityId() !== requestEntityId) return;
      if (already_queued) toast.info("Joining the validation already running for this month");
      router.push(`/payroll/validation?job=${encodeURIComponent(job.id)}`);
    } catch (err) {
      if (getActiveEntityId() !== requestEntityId) return;
      setError({ stage: "queueing", message: err instanceof Error ? err.message : "Validation could not be started." });
      setPhase("checked");
    }
  };

  const downloadTemplate = async () => {
    try {
      const res = await apiFetch("/api/payroll/template.csv");
      if (!res.ok) throw new Error("Could not download the template.");
      saveBlob(await res.blob(), "salary-register-template.csv");
    } catch (err) { toast.error(err instanceof Error ? err.message : "Download failed."); }
  };

  const stepState = (i: number): StepState => {
    const order: Phase[][] = [["choose", "parsing"], ["map", "checking"], ["checked"], ["queueing"]];
    const at = order.findIndex((p) => p.includes(phase));
    if (error && ((i === 0 && error.stage === "parsing") || (i === 1 && error.stage === "checking") || (i === 3 && error.stage === "queueing"))) return "error";
    return i < at ? "done" : i === at ? "current" : "todo";
  };
  const needsArrearDates = runType !== "regular";

  const rows = useMemo(() => {
    if (!preview) return [];
    const q = query.trim().toLowerCase();
    return preview.columns.filter((c) => {
      if (show === "mapped" && !mapping[c]) return false;
      if (show === "unmapped" && mapping[c]) return false;
      return !q || c.toLowerCase().includes(q) || (mapping[c] ?? "").includes(q.replaceAll(" ", "_"));
    });
  }, [preview, query, show, mapping]);

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <PageHeader
        title="Salary register"
        description="Bring in the month's register from your payroll system, map its columns once, and queue a full statutory validation. Validation runs on the server; you can close the page."
        actions={
          <>
            <Button variant="outline" onClick={() => void downloadTemplate()}><Download size={14} /> Template</Button>
            <Button variant="outline" asChild><Link href="/payroll/history"><History size={14} /> Register history</Link></Button>
          </>
        }
      />

      {!canWrite ? (
        <AlertBanner variant="info">Your role can view registers but not upload them. Ask an analyst, manager or owner.</AlertBanner>
      ) : null}

      {activeJobs.length > 0 ? (
        <AlertBanner variant="info" title="A validation is still running">
          {activeJobs.map((job) => (
            <span key={job.id} className="mt-0.5 flex flex-wrap items-center gap-2">
              {monthLabel(job.period_month)} · {job.stage_label}
              {job.employee_total ? ` · ${count(job.employee_done)} of ${count(job.employee_total)} employees` : ""}
              <Link className="font-medium underline" href={`/payroll/validation?job=${encodeURIComponent(job.id)}`}>View progress</Link>
            </span>
          ))}
        </AlertBanner>
      ) : null}

      <div className="rounded-xl border border-ink-200 bg-white px-4 py-3 shadow-soft">
        <Stepper
          label="Upload progress"
          steps={[
            { label: "Choose file", state: stepState(0), note: file ? file.name : "CSV or Excel" },
            { label: "Map columns", state: stepState(1), note: preview ? `${Object.keys(mapping).length} of ${preview.columns.length} mapped` : undefined },
            { label: "Server check", state: stepState(2), note: checked ? `${plural(checked.employee_count, "employee")} read` : undefined },
            { label: "Validate", state: stepState(3) },
          ]}
        />
      </div>

      {/* ── 1. Choose ─────────────────────────────────────────────── */}
      <section className="rounded-xl border border-ink-200 bg-white shadow-soft" aria-labelledby="s1">
        <header className="border-b border-ink-100 px-5 py-3">
          <h2 id="s1" className="text-[15px] font-semibold text-ink-900">1 · Choose the file and the month</h2>
        </header>
        <div className="grid gap-5 p-5 lg:grid-cols-[1.2fr_1fr]">
          <div>
            <div
              className={cn(
                "flex min-h-[9.5rem] flex-col items-center justify-center rounded-lg border border-dashed px-5 py-6 text-center transition-colors",
                drag ? "border-brand-500 bg-brand-50" : file ? "border-success-300 bg-success-50/50" : "border-ink-300 bg-ink-50/50",
              )}
              onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files?.[0]; if (f) reset(f); }}
            >
              {file ? (
                <div className="flex items-center gap-3 text-left">
                  <FileSpreadsheet className="h-8 w-8 flex-shrink-0 text-success-600" strokeWidth={1.5} aria-hidden />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-ink-900">{file.name}</p>
                    <p className="text-xs text-ink-500">{(file.size / 1024).toLocaleString("en-IN", { maximumFractionDigits: 1 })} KB · not yet read</p>
                  </div>
                  <Button variant="ghost" size="icon-sm" aria-label="Remove file" onClick={() => reset(null)}><X size={14} /></Button>
                </div>
              ) : (
                <>
                  <UploadCloud className="h-7 w-7 text-ink-500" strokeWidth={1.5} aria-hidden />
                  <p className="mt-2 text-sm text-ink-700">Drop the register here, or</p>
                  <label className="mt-2 inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-lg border border-ink-200 bg-white px-3.5 text-[13px] font-medium text-ink-800 shadow-soft hover:bg-ink-50 focus-within:outline focus-within:outline-2 focus-within:outline-brand-600">
                    Choose a file
                    <input type="file" accept=".csv,.xlsx" className="sr-only" onChange={(e) => reset(e.target.files?.[0] || null)} disabled={!canWrite} />
                  </label>
                  <p className="mt-2 text-xs text-ink-500">.csv or .xlsx, one row per employee, headers in the first row</p>
                </>
              )}
            </div>
            <div className="mt-3 rounded-lg bg-ink-50 p-3 text-xs leading-relaxed text-ink-600">
              <p className="font-medium text-ink-800">What the file needs</p>
              <p className="mt-0.5">
                An <b>Employee ID</b> column
                {components === null ? "" : components.length
                  ? <>, and with the strict check on, a column for each of your {components.length} salary components ({components.slice(0, 6).join(", ")}{components.length > 6 ? `, and ${components.length - 6} more` : ""})</>
                  : <>. No salary components are configured yet — <Link href="/config/components" className="underline">set them up</Link> before validating</>}
                . Statutory columns (PF, ESI, PT, TDS, gross, net, days) are read when present; a check whose input is missing is reported as <i>cannot validate</i>, never as passed.
              </p>
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <label htmlFor="period" className="text-[13px] font-medium text-ink-800">Payroll month</label>
              <input
                id="period"
                type="month"
                value={periodMonth}
                onChange={(e) => { setPeriodMonth(normalisePeriod(e.target.value) ?? ""); setChecked(null); if (phase === "checked") setPhase("map"); }}
                className="mt-1 block h-9 w-full max-w-[14rem] rounded-lg border border-ink-200 bg-white px-3 text-[13px] shadow-soft focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
                aria-describedby="period-help"
              />
              <p id="period-help" className="mt-1 text-xs text-ink-500">
                {working.source === "chosen" && periodMonth === working.period ? "Filled from your working period. " : ""}
                Uploading again for the same month adds a new revision; earlier revisions and their runs are kept.
              </p>
            </div>
            <fieldset>
              <legend className="text-[13px] font-medium text-ink-800">Run type</legend>
              <div className="mt-1 space-y-1.5">
                {RUN_TYPES.map((t) => (
                  <label key={t.id} className={cn("flex cursor-pointer gap-2.5 rounded-lg border px-3 py-2", runType === t.id ? "border-brand-300 bg-brand-50/60" : "border-ink-200 hover:bg-ink-50")}>
                    <input type="radio" name="run-type" className="mt-0.5 accent-brand-600" checked={runType === t.id} onChange={() => setRunType(t.id)} />
                    <span>
                      <span className="block text-[13px] font-medium text-ink-900">{t.label}</span>
                      <span className="block text-xs text-ink-500">{t.desc}</span>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
            {needsArrearDates ? (
              <div className="grid grid-cols-2 gap-3">
                <label className="text-[13px] font-medium text-ink-800">Effective from
                  <input type="date" className="mt-1 block h-9 w-full rounded-lg border border-ink-200 px-2.5 text-[13px]" value={from} onChange={(e) => setFrom(e.target.value)} />
                </label>
                <label className="text-[13px] font-medium text-ink-800">Effective to
                  <input type="date" className="mt-1 block h-9 w-full rounded-lg border border-ink-200 px-2.5 text-[13px]" value={to} onChange={(e) => setTo(e.target.value)} />
                </label>
              </div>
            ) : null}
            <label className="flex cursor-pointer items-start gap-2.5">
              <input type="checkbox" className="mt-0.5 accent-brand-600" checked={strict} onChange={(e) => setStrict(e.target.checked)} />
              <span>
                <span className="block text-[13px] font-medium text-ink-900">Strict header check (recommended)</span>
                <span className="block text-xs text-ink-500">Every configured salary component must have a column. Off, a missing component column is treated as zero and reported as a notice.</span>
              </span>
            </label>
          </div>
        </div>
        <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-ink-100 px-5 py-3">
          {error?.stage === "parsing" ? <p className="mr-auto text-[13px] text-danger-700" role="alert">The file could not be read: {error.message}</p> : null}
          <Button onClick={() => void parse()} disabled={!file || !canWrite || phase === "parsing"}>
            {phase === "parsing" ? <><Loader2 size={14} className="animate-spin" /> Reading file…</> : preview ? "Read the file again" : "Read file and map columns"}
          </Button>
        </footer>
      </section>

      {/* ── 2. Map ────────────────────────────────────────────────── */}
      {preview ? (
        <section className="rounded-xl border border-ink-200 bg-white shadow-soft" aria-labelledby="s2">
          <header className="flex flex-wrap items-center gap-3 border-b border-ink-100 px-5 py-3">
            <h2 id="s2" className="text-[15px] font-semibold text-ink-900">2 · Map columns</h2>
            <span className="text-xs text-ink-500">{plural(preview.employee_count, "row")} · {plural(preview.columns.length, "column")} in the file</span>
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <label className="sr-only" htmlFor="format">Saved format</label>
              <select id="format" className="h-8 rounded-lg border border-ink-200 bg-white px-2 text-[13px]" value={profiles.some((p) => p.name === profileName) ? profileName : ""} onChange={(e) => applyProfile(e.target.value)}>
                <option value="">{profiles.length ? "Apply a saved format…" : "No saved formats yet"}</option>
                {profiles.map((p) => <option key={p.id} value={p.name}>{p.name}</option>)}
              </select>
            </div>
          </header>

          <div className="grid gap-0 lg:grid-cols-[1fr_17rem]">
            <div className="min-w-0 border-ink-100 lg:border-r">
              <div className="flex flex-wrap items-center gap-2 border-b border-ink-100 px-4 py-2.5">
                <div className="relative min-w-[12rem] flex-1">
                  <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-500" aria-hidden />
                  <input
                    type="search"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Search columns or fields"
                    aria-label="Search columns or fields"
                    className="h-8 w-full rounded-lg border border-ink-200 bg-white pl-8 pr-2 text-[13px] focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
                  />
                </div>
                <div className="flex rounded-lg border border-ink-200 p-0.5 text-xs" role="group" aria-label="Show columns">
                  {(["all", "unmapped", "mapped"] as const).map((k) => (
                    <button key={k} type="button" aria-pressed={show === k} onClick={() => setShow(k)}
                      className={cn("rounded-md px-2 py-1 capitalize", show === k ? "bg-ink-900 text-white" : "text-ink-600 hover:bg-ink-50")}>
                      {k}
                    </button>
                  ))}
                </div>
              </div>
              <div className="scrollbar-thin max-h-[28rem] overflow-auto">
                <table className="w-full min-w-[40rem] border-separate border-spacing-0 text-[13px]">
                  <thead>
                    <tr className="[&>th]:sticky [&>th]:top-0 [&>th]:z-10 [&>th]:border-b [&>th]:border-ink-200 [&>th]:bg-ink-50 [&>th]:px-3 [&>th]:py-2 [&>th]:text-left [&>th]:text-xs [&>th]:font-medium [&>th]:text-ink-500">
                      <th scope="col">Column in your file</th>
                      <th scope="col">Sample values</th>
                      <th scope="col">Maps to</th>
                      <th scope="col">Match</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((source) => {
                      const samples = preview.preview.map((r) => r[source]).filter((v) => v !== "" && v !== null && v !== undefined).slice(0, 2);
                      const dest = mapping[source] ?? "";
                      return (
                        <tr key={source} className="[&>td]:border-b [&>td]:border-ink-100 [&>td]:px-3 [&>td]:py-1.5">
                          <td className="max-w-[14rem]"><span className="block truncate font-medium text-ink-900" title={source}>{source}</span></td>
                          <td className="max-w-[12rem]">
                            <span className="block truncate font-mono text-xs text-ink-600" title={samples.map(String).join(", ")}>
                              {samples.length ? samples.map(String).join(", ") : <span className="font-sans text-ink-500">empty in the first rows</span>}
                            </span>
                          </td>
                          <td>
                            <select
                              aria-label={`Destination for ${source}`}
                              value={dest}
                              onChange={(e) => setDestination(source, e.target.value)}
                              className={cn("h-8 w-full min-w-[11rem] rounded-lg border bg-white px-2 text-[13px]", dest ? "border-ink-200" : "border-dashed border-ink-300 text-ink-500")}
                            >
                              <option value="">Not imported</option>
                              {preview.destinations.map((d) => (
                                <option key={d} value={d} disabled={!!mappedTo[d] && mappedTo[d] !== source}>
                                  {human(d)}{required.includes(d) ? " (required)" : ""}{mappedTo[d] && mappedTo[d] !== source ? ` — used by ${mappedTo[d]}` : ""}
                                </option>
                              ))}
                            </select>
                          </td>
                          <td className="whitespace-nowrap">
                            {dest ? (
                              <Badge variant={origin[source] === "exact" || origin[source] === "profile" ? "success" : origin[source] === "alias" ? "primary" : "secondary"}>
                                {ORIGIN_LABEL[origin[source] ?? "manual"]}
                              </Badge>
                            ) : <span className="text-xs text-ink-500">Ignored</span>}
                          </td>
                        </tr>
                      );
                    })}
                    {rows.length === 0 ? (
                      <tr><td colSpan={4} className="px-3 py-6 text-center text-[13px] text-ink-500">No columns match “{query}”.</td></tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </div>

            <aside className="space-y-3 p-4" aria-label="Required fields">
              <div>
                <p className="text-[13px] font-medium text-ink-900">Required {strict ? "" : "(strict check off)"}</p>
                <ul className="mt-1.5 space-y-1">
                  {required.map((r) => (
                    <li key={r} className="flex items-center gap-2 text-xs">
                      {mappedTo[r] ? <Check size={13} className="text-success-600" aria-label="Mapped" /> : <CircleDashed size={13} className="text-danger-600" aria-label="Not mapped" />}
                      <span className={cn(mappedTo[r] ? "text-ink-700" : "font-medium text-danger-700")}>{human(r)}</span>
                      {mappedTo[r] ? <span className="ml-auto truncate text-ink-500" title={mappedTo[r]}>{mappedTo[r]}</span> : <span className="ml-auto text-danger-700">missing</span>}
                    </li>
                  ))}
                </ul>
              </div>
              <p className="text-xs leading-relaxed text-ink-500">
                Unmapped columns are not imported — an unknown column is never guessed to be an earning or a deduction.
              </p>
              <label className="block text-xs font-medium text-ink-800">
                Save this mapping as a format (optional)
                <input className="mt-1 block h-8 w-full rounded-lg border border-ink-200 px-2 text-[13px]" value={profileName} maxLength={100}
                  onChange={(e) => setProfileName(e.target.value)} placeholder="e.g. Darwinbox monthly" />
              </label>
            </aside>
          </div>

          <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-ink-100 px-5 py-3">
            <p className="mr-auto text-xs text-ink-500" role={error?.stage === "checking" || unmappedRequired.length || monthNeeded ? "status" : undefined}>
              {error?.stage === "checking" ? <span className="text-danger-700">The server did not accept the register: {error.message}</span>
                : unmappedRequired.length ? <>Map {unmappedRequired.map(human).join(", ")} to continue{strict && unmappedRequired.some((r) => r !== "employee_id") ? ", or turn off the strict header check" : ""}.</>
                  : monthNeeded ? "Choose the payroll month above to continue." : "Ready for the server check."}
            </p>
            <Button onClick={() => void check()} disabled={!canWrite || !!unmappedRequired.length || monthNeeded || phase === "checking"}>
              {phase === "checking" ? <><Loader2 size={14} className="animate-spin" /> Checking…</> : checked ? "Check again" : "Upload and check"}
            </Button>
          </footer>
        </section>
      ) : null}

      {/* ── 3. Checked ───────────────────────────────────────────── */}
      {checked ? (
        <section className="rounded-xl border border-ink-200 bg-white shadow-soft" aria-labelledby="s3">
          <header className="border-b border-ink-100 px-5 py-3">
            <h2 id="s3" className="text-[15px] font-semibold text-ink-900">3 · What the server read</h2>
          </header>
          <div className="grid gap-4 p-5 md:grid-cols-4">
            <Fact label="Employees read" value={count(checked.employee_count)} />
            <Fact label="Columns imported" value={count(checked.columns.length)} note={`${count((preview?.columns.length ?? 0) - Object.keys(mapping).length)} ignored`} />
            <Fact label="Revision" value={`${checked.upload.revision}`} note={`for ${monthLabel(checked.upload.period_month)}`} />
            <Fact
              label="Month's register"
              value={checked.upload.stored_as_register ? "Replaced" : "Unchanged"}
              note={checked.upload.stored_as_register ? "cost and dashboards use this file" : "validated only"}
            />
          </div>
          <div className="space-y-3 px-5 pb-4">
            {checked.upload.revision > 1 ? (
              <p className="text-xs text-ink-500">
                Revision {checked.upload.revision}: earlier revisions for this month are kept with the runs that read them. The month&apos;s current run describes the old file until you validate this one.
              </p>
            ) : null}
            {checked.missing_required.length ? (
              <AlertBanner variant="warning" title="This register cannot be validated as uploaded">
                Missing required column{checked.missing_required.length > 1 ? "s" : ""}: {checked.missing_required.join(", ")}. Map them in step 2, or add them to the file.
              </AlertBanner>
            ) : null}
            {checked.warnings.length ? (
              <AlertBanner variant="info" title={`${plural(checked.warnings.length, "notice")} from the server`}>
                <ul className="list-disc space-y-0.5 pl-4">{checked.warnings.slice(0, 8).map((w) => <li key={w}>{w}</li>)}</ul>
                {checked.warnings.length > 8 ? <p className="mt-1">and {checked.warnings.length - 8} more.</p> : null}
              </AlertBanner>
            ) : null}
            <p className="text-xs text-ink-500">
              Rows are not rejected at upload. A row with a wrong or missing value is reported by validation as a finding against that employee, with the row it came from.
            </p>
          </div>
          {checked.preview.length ? (
            <div className="scrollbar-thin overflow-x-auto border-t border-ink-100">
              <table className="w-full border-separate border-spacing-0 text-xs">
                <caption className="px-5 py-2 text-left text-xs text-ink-500">First {checked.preview.length} rows, as imported</caption>
                <thead>
                  <tr className="[&>th]:border-b [&>th]:border-ink-200 [&>th]:bg-ink-50 [&>th]:px-3 [&>th]:py-2 [&>th]:text-left [&>th]:font-medium [&>th]:text-ink-500">
                    {Object.keys(checked.preview[0]).filter((k) => !k.startsWith("_")).map((k) => <th key={k} scope="col" className="whitespace-nowrap">{human(k)}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {checked.preview.map((row, idx) => (
                    <tr key={idx} className="[&>td]:border-b [&>td]:border-ink-100 [&>td]:px-3 [&>td]:py-1.5">
                      {Object.entries(row).filter(([k]) => !k.startsWith("_")).map(([k, v]) => (
                        <td key={k} className={cn("whitespace-nowrap", typeof v === "number" && "num text-right")}>
                          {v === null || v === undefined || v === "" ? <span className="text-ink-300">—</span> : typeof v === "number" ? v.toLocaleString("en-IN") : String(v)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-ink-100 px-5 py-3">
            {error?.stage === "queueing" ? <p className="mr-auto text-[13px] text-danger-700" role="alert">{error.message}</p> : null}
            <Button onClick={() => void validate()} disabled={!canWrite || checked.missing_required.length > 0 || phase === "queueing"}>
              {phase === "queueing" ? <><Loader2 size={14} className="animate-spin" /> Queuing…</> : <><ShieldCheck size={14} /> Run validation</>}
            </Button>
          </footer>
        </section>
      ) : null}
    </div>
  );
}

function Fact({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div>
      <p className="text-xs text-ink-500">{label}</p>
      <p className="num mt-0.5 text-lg font-semibold text-ink-900">{value}</p>
      {note ? <p className="text-xs text-ink-500">{note}</p> : null}
    </div>
  );
}
