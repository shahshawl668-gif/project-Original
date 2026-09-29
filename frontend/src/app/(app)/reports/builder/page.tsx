"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, Download, Loader2, Save } from "lucide-react";

import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import { PageHeader } from "@/components/layout/PageHeader";
import { apiBlob, apiJson } from "@/lib/api";
import { fetchDimensions, fetchPeriods } from "@/lib/cost-analysis";

type Field = { key: string; label: string; numeric: boolean };
type Dataset = { key: string; label: string; grain: string; fields: Field[]; dimensions: { key: string; label: string }[]; note: string };
type Spec = { dataset: "payroll_cost"; dimension: string; fields: string[]; filters: Record<string, string[]>; date_from: string | null; date_to: string | null; sort: string; order: "asc" | "desc"; calculations: { key: string; label: string; expression: string }[] };
type Preview = { status: "ok" | "missing_data" | "no_matching_records"; rows: Record<string, string | number | null>[]; record_count: number; truncated_preview?: boolean; control_totals: Record<string, number> | null; grain: string };
type Saved = { id: string; name: string; version: number; visibility: string; status: string; specification: Spec };
const steps = ["Dataset", "Fields", "Filters", "Calculations", "Grouping", "Layout", "Preview", "Save"];
const initial: Spec = { dataset: "payroll_cost", dimension: "department", fields: ["period", "dimension", "headcount", "gross", "ctc"], filters: {}, date_from: null, date_to: null, sort: "period", order: "asc", calculations: [] };

export default function ReportBuilderPage() {
  const queryClient = useQueryClient();
  const [step, setStep] = useState(0);
  const [spec, setSpec] = useState<Spec>(initial);
  const [name, setName] = useState("Payroll cost by department");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [visibility, setVisibility] = useState<"private" | "shared">("private");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const datasets = useQuery({ queryKey: ["reports", "datasets"], queryFn: () => apiJson<{ datasets: Dataset[] }>("/api/reports/builder/datasets") });
  const saved = useQuery({ queryKey: ["reports", "saved"], queryFn: () => apiJson<{ reports: Saved[] }>("/api/reports/builder/saved") });
  const versions = useQuery({ queryKey: ["reports", "versions", activeId], enabled: !!activeId, queryFn: () => apiJson<{ versions: { version: number; name: string; created_at: string }[] }>(`/api/reports/builder/saved/${activeId}/versions`) });
  const dimensions = useQuery({ queryKey: ["bi", "dimensions"], queryFn: fetchDimensions });
  const periods = useQuery({ queryKey: ["bi", "periods"], queryFn: fetchPeriods });
  const dataset = datasets.data?.datasets[0];
  const fields = [...(dataset?.fields ?? []), ...spec.calculations.map((c) => ({ key: c.key, label: c.label, numeric: true }))];

  function update(next: Partial<Spec>) { setSpec((s) => ({ ...s, ...next })); setPreview(null); setSavedMessage(null); }
  async function runPreview() {
    setBusy(true); setError(null);
    try {
      setPreview(await apiJson<Preview>("/api/reports/builder/preview", { method: "POST", body: JSON.stringify({ specification: spec }) }));
      setStep(6);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function save() {
    setBusy(true); setError(null);
    try {
      const result = await apiJson<Saved>(activeId ? `/api/reports/builder/saved/${activeId}` : "/api/reports/builder/saved", {
        method: activeId ? "PUT" : "POST", body: JSON.stringify({ name: name.trim(), specification: spec, visibility, status: "draft" }),
      });
      setActiveId(result.id);
      setSavedMessage(`Saved draft version ${result.version}. It will use current data when previewed again.`);
      await saved.refetch(); await queryClient.invalidateQueries({ queryKey: ["reports", "versions", result.id] });
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  function load(report: Saved) {
    setSpec(report.specification); setName(report.name); setVisibility(report.visibility as "private" | "shared"); setPreview(null);
    setActiveId(report.id);
    setSavedMessage(`Editing ${report.name}, version ${report.version}. Preview uses current data.`); setStep(1);
  }

  async function clone(report: Saved) {
    setBusy(true); setError(null);
    try {
      const copy = await apiJson<Saved>(`/api/reports/builder/saved/${report.id}/clone`, { method: "POST" });
      load(copy); await saved.refetch();
      setSavedMessage(`Created personal draft ${copy.name}.`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function download() {
    if (!activeId) return;
    setBusy(true); setError(null);
    try {
      const blob = await apiBlob(`/api/reports/builder/saved/${activeId}.xlsx`);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url; link.download = `peopleops-report-${activeId.slice(0, 12)}.xlsx`;
      document.body.appendChild(link); link.click(); link.remove();
      URL.revokeObjectURL(url);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  return <div className="space-y-5">
    <PageHeader eyebrow="PeopleOps Reports" title="Report Builder" description="Build a payroll management report using approved BI figures. One row represents one payroll month and one breakdown value." />
    <Link href="/reports" className="inline-flex items-center gap-2 text-sm text-brand-600 hover:underline"><ArrowLeft size={15} /> Report Centre</Link>
    {(datasets.isError || saved.isError) && <AlertBanner variant="error" title="Could not load Report Builder">{String((datasets.error || saved.error) as Error)}</AlertBanner>}
    {error && <AlertBanner variant="error" title="Report action failed">{error}</AlertBanner>}
    {savedMessage && <AlertBanner variant="success" title="Report saved">{savedMessage}</AlertBanner>}
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_280px]">
      <Card><CardContent className="space-y-5 py-5">
        <nav aria-label="Builder steps" className="flex flex-wrap gap-2">
          {steps.map((label, index) => <button key={label} type="button" onClick={() => setStep(index)}
            aria-current={step === index ? "step" : undefined}
            className={`rounded-full px-3 py-1.5 text-xs font-medium ${step === index ? "bg-brand-600 text-white" : "bg-ink-50 text-ink-600"}`}>
            {index + 1}. {label}
          </button>)}
        </nav>
        <h2 className="text-xl font-semibold text-ink-900">{steps[step]}</h2>
        {step === 0 && <div className="space-y-3">
          <p className="text-sm text-ink-600">Payroll cost is the first approved dataset. It uses the same cost calculations as Insights and preserves unassigned dimensions.</p>
          <div className="rounded-xl border border-ink-200 p-4">
            <h3 className="font-semibold">{dataset?.label ?? "Loading dataset…"}</h3>
            <p className="mt-1 text-sm text-ink-500">Grain: {dataset?.grain}. {dataset?.note}</p>
          </div>
        </div>}
        {step === 1 && <div className="grid gap-2 sm:grid-cols-2">
          {fields.map((field) => <label key={field.key} className="flex items-center gap-2 rounded-lg border border-ink-200 p-3 text-sm">
            <input type="checkbox" checked={spec.fields.includes(field.key)} onChange={() => {
              const next = spec.fields.includes(field.key) ? spec.fields.filter((x) => x !== field.key) : [...spec.fields, field.key];
              if (next.length) update({ fields: next, sort: next.includes(spec.sort) ? spec.sort : next[0] });
            }} />{field.label}
          </label>)}
          <p className="text-xs text-ink-500 sm:col-span-2">The selected order is the column order. Employee details are not part of this aggregate dataset.</p>
        </div>}
        {step === 2 && <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            {(["date_from", "date_to"] as const).map((key) => <label key={key} className="space-y-1 text-sm">
              <span>{key === "date_from" ? "From period" : "To period"}</span>
              <select className="w-full rounded-lg border p-2" value={spec[key] ?? ""} onChange={(e) => update({ [key]: e.target.value || null })}>
                <option value="">All available</option>
                {(periods.data?.periods ?? []).map((p) => <option key={p.period} value={p.period}>{p.label}</option>)}
              </select>
            </label>)}
          </div>
          <label className="block space-y-1 text-sm">Filter dimension
            <select className="block w-full rounded-lg border p-2" value={Object.keys(spec.filters)[0] ?? ""} onChange={(e) => update({ filters: e.target.value ? { [e.target.value]: [] } : {} })}>
              <option value="">No filter</option>
              {(dimensions.data?.dimensions ?? []).map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}
            </select>
          </label>
          {Object.keys(spec.filters).map((key) => <div key={key} className="max-h-44 space-y-1 overflow-auto rounded-lg border p-3">
            {(dimensions.data?.dimensions.find((d) => d.key === key)?.values ?? []).map((value) => <label key={value} className="flex gap-2 text-sm">
              <input type="checkbox" checked={spec.filters[key].includes(value)} onChange={() => update({ filters: { [key]: spec.filters[key].includes(value) ? spec.filters[key].filter((x) => x !== value) : [...spec.filters[key], value] } })} />{value}
            </label>)}
          </div>)}
        </div>}
        {step === 3 && <div className="space-y-3 text-sm">
          <p>Optional advanced calculation. Use gross, deductions, net, employer_cost, ctc, headcount or person_months with +, −, × and ÷. Division by zero returns blank.</p>
          <label className="block space-y-1">Column label<input className="block w-full rounded-lg border p-2" value={spec.calculations[0]?.label ?? ""} onChange={(e) => update({ calculations: [{ key: "calc_custom", label: e.target.value, expression: spec.calculations[0]?.expression ?? "" }] })} /></label>
          <label className="block space-y-1">Expression<input className="block w-full rounded-lg border p-2" placeholder="ctc / headcount" value={spec.calculations[0]?.expression ?? ""} onChange={(e) => update({ calculations: [{ key: "calc_custom", label: spec.calculations[0]?.label ?? "Custom measure", expression: e.target.value }] })} /></label>
          <button type="button" className="text-brand-600" onClick={() => update({ calculations: [], fields: spec.fields.filter((x) => x !== "calc_custom"), sort: spec.sort === "calc_custom" ? "period" : spec.sort })}>Clear calculation</button>
        </div>}
        {step === 4 && <label className="block space-y-2 text-sm">Group rows by
          <select className="block w-full rounded-lg border p-2" value={spec.dimension} onChange={(e) => update({ dimension: e.target.value })}>
            {(dataset?.dimensions ?? []).map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}
          </select>
          <p className="text-xs text-ink-500">One row per month and group. Totals use the shared BI calculation, not a join to a component table.</p>
        </label>}
        {step === 5 && <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm">Sort column<select className="mt-1 block w-full rounded-lg border p-2" value={spec.sort} onChange={(e) => update({ sort: e.target.value })}>{spec.fields.map((key) => <option key={key} value={key}>{fields.find((f) => f.key === key)?.label ?? key}</option>)}</select></label>
          <label className="text-sm">Order<select className="mt-1 block w-full rounded-lg border p-2" value={spec.order} onChange={(e) => update({ order: e.target.value as "asc" | "desc" })}><option value="asc">Ascending</option><option value="desc">Descending</option></select></label>
          <p className="text-xs text-ink-500 sm:col-span-2">This release supports an aggregate detail table. Pivot and PDF layouts require the report job phase.</p>
        </div>}
        {step === 6 && <div className="space-y-3">
          <button type="button" onClick={runPreview} disabled={busy} className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">{busy ? "Calculating…" : "Generate preview"}</button>
          {preview && <div className="space-y-2">
            <p className="text-sm font-medium">{preview.status === "ok" ? `${preview.record_count} rows matched` : preview.status === "missing_data" ? "No salary register for this period" : "No records match these filters"}</p>
            {preview.truncated_preview && <p className="text-xs text-amber-700">Preview shows the first 200 rows; the total matched count is shown above.</p>}
            {preview.control_totals && <p className="text-xs text-ink-500">Control total CTC: {Number(preview.control_totals.ctc).toLocaleString("en-IN")}. Grain: {preview.grain}.</p>}
            <div className="max-h-96 overflow-auto rounded-lg border"><table className="min-w-full text-left text-xs"><thead className="sticky top-0 bg-ink-50"><tr>{spec.fields.map((key) => <th key={key} className="whitespace-nowrap p-2">{fields.find((f) => f.key === key)?.label ?? key}</th>)}</tr></thead><tbody>{preview.rows.map((row, i) => <tr key={i} className="border-t">{spec.fields.map((key) => <td key={key} className="whitespace-nowrap p-2">{row[key] ?? "—"}</td>)}</tr>)}</tbody></table></div>
          </div>}
        </div>}
        {step === 7 && <div className="space-y-3">
          <label className="block text-sm">Report name<input className="mt-1 block w-full rounded-lg border p-2" value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label className="block text-sm">Visibility<select className="mt-1 block w-full rounded-lg border p-2" value={visibility} onChange={(e) => setVisibility(e.target.value as "private" | "shared")}><option value="private">Personal draft</option><option value="shared">Company shared (manager access)</option></select></label>
          <p className="text-xs text-ink-500">A saved definition contains choices, not a frozen result. Access is checked again when previewed.</p>
          <button type="button" disabled={busy || !name.trim()} onClick={save} className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">{busy ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />} {activeId ? "Save new version" : "Save draft"}</button>
          {activeId && <button type="button" disabled={busy || !spec.date_from || !spec.date_to} onClick={download} className="ml-2 inline-flex items-center gap-2 rounded-lg border px-4 py-2 text-sm font-semibold disabled:opacity-50"><Download size={15} /> Download Excel</button>}
          {activeId && (!spec.date_from || !spec.date_to) && <p className="text-xs text-ink-500">Choose both period bounds before export.</p>}
          {activeId && <div className="space-y-1 text-xs text-ink-500"><strong className="block text-ink-700">Definition history</strong>{(versions.data?.versions ?? []).map((item) => <p key={item.version}>Version {item.version} · {item.name} · {item.created_at ? new Date(item.created_at).toLocaleString() : "Recorded"}</p>)}</div>}
        </div>}
        <div className="flex justify-between border-t pt-4">
          <button type="button" disabled={step === 0} onClick={() => setStep((n) => n - 1)} className="rounded-lg border px-3 py-2 text-sm disabled:opacity-40">Back</button>
          {step < 7 && <button type="button" onClick={() => setStep((n) => n + 1)} className="inline-flex items-center gap-1 rounded-lg bg-brand-600 px-3 py-2 text-sm text-white">{step === 6 ? <Check size={14} /> : <ArrowRight size={14} />} Next</button>}
        </div>
      </CardContent></Card>
      <Card><CardContent className="space-y-3 py-5">
        <h2 className="font-semibold">Saved reports</h2>
        <p className="text-xs text-ink-500">Personal drafts and reports shared with this company.</p>
        {(saved.data?.reports ?? []).map((report) => <div key={report.id} className="rounded-lg border p-3 text-sm">
          <span className="block font-medium">{report.name}</span><span className="text-xs text-ink-500">{report.visibility} · v{report.version} · {report.status}</span>
          <div className="mt-2 flex gap-3"><button type="button" onClick={() => load(report)} className="text-brand-600 hover:underline">Open</button><button type="button" onClick={() => clone(report)} className="text-brand-600 hover:underline">Clone</button></div>
        </div>)}
        {saved.data?.reports.length === 0 && <p className="text-sm text-ink-500">No saved reports yet.</p>}
      </CardContent></Card>
    </div>
  </div>;
}
