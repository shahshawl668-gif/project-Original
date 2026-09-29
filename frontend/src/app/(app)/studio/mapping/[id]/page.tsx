"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import * as XLSX from "xlsx";
import { ArrowLeft, Copy, Eye, FileUp, GitCompare, Plus, Save, Send, Trash2 } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StudioNav } from "@/components/studio/StudioNav";
import {
  OBJECT_LABEL,
  studioConnApi,
  studioMapApi,
  type MappingField,
  type MappingSpec,
  type PreviewResult,
} from "@/lib/studio";
import { cn } from "@/lib/utils";

const FIELD =
  "w-full rounded-lg border border-ink-200 bg-white px-2 py-1.5 text-sm text-ink-900";
const MANAGE = new Set(["owner", "manager"]);
const WRITE = new Set(["owner", "manager", "analyst"]);

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");

function linesToTable(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  text.split("\n").forEach((line) => {
    const i = line.indexOf("=");
    if (i > 0) out[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  });
  return out;
}
const tableToLines = (t?: Record<string, string>) => Object.entries(t ?? {}).map(([k, v]) => `${k}=${v}`).join("\n");

/** Read a CSV or Excel file in the browser, as text, so "0042" stays "0042". */
async function readSample(file: File): Promise<Record<string, unknown>[]> {
  const isCsv = file.name.toLowerCase().endsWith(".csv");
  const wb = isCsv ? XLSX.read(await file.text(), { type: "string", raw: true }) : XLSX.read(await file.arrayBuffer(), { type: "array" });
  const ws = wb.Sheets[wb.SheetNames[0]];
  return XLSX.utils.sheet_to_json<Record<string, unknown>>(ws, { raw: false, defval: null }).slice(0, 500);
}

export default function MappingEditorPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { entity, activeRole } = useEntity();
  const qc = useQueryClient();
  const canWrite = WRITE.has(activeRole ?? "");
  const canPublish = MANAGE.has(activeRole ?? "");
  const version = useQuery({ queryKey: ["studio-mapping", entity?.id, id], queryFn: () => studioMapApi.get(id), enabled: !!entity && !!id, retry: false });
  const profiles = useQuery({ queryKey: ["studio-mappings", entity?.id], queryFn: studioMapApi.list, enabled: !!entity });
  const targets = useQuery({ queryKey: ["studio-map-targets", entity?.id, version.data?.object_type], queryFn: () => studioMapApi.targets(version.data!.object_type), enabled: !!version.data });
  const connections = useQuery({ queryKey: ["studio-connections", entity?.id], queryFn: studioConnApi.list, enabled: !!entity });

  const [spec, setSpec] = useState<MappingSpec | null>(null);
  const [reason, setReason] = useState("");
  const [sample, setSample] = useState<Record<string, unknown>[]>([]);
  const [json, setJson] = useState("");
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [compareWith, setCompareWith] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (version.data) { setSpec(version.data.spec); setReason(version.data.change_reason ?? ""); } }, [version.data]);

  const sampleFields = useMemo(() => Array.from(new Set(sample.flatMap((r) => Object.keys(r ?? {})))).sort(), [sample]);
  const siblings = profiles.data?.find((p) => p.key === version.data?.key)?.versions ?? [];
  const compare = useQuery({ queryKey: ["studio-map-compare", id, compareWith], queryFn: () => studioMapApi.compare(id, compareWith), enabled: !!compareWith });

  if (version.error) return <AlertBanner variant="error" title="This mapping could not be opened">It may belong to another company. <Link className="underline" href="/studio/mapping">All mappings</Link></AlertBanner>;
  const v = version.data;
  if (!v || !spec) return <Skeleton className="h-96 w-full rounded-2xl" />;
  const draft = v.status === "draft";
  const editable = draft && canWrite;

  const setField = (i: number, patch: Partial<MappingField>) => setSpec({ ...spec, fields: spec.fields.map((f, j) => (j === i ? { ...f, ...patch } : f)) });
  const removeField = (i: number) => setSpec({ ...spec, fields: spec.fields.filter((_, j) => j !== i) });
  const addField = () => setSpec({ ...spec, fields: [...spec.fields, { target: "", source: "", type: "text" }] });
  const suggest = () => {
    const have = new Set(spec.fields.map((f) => f.target));
    const extra: MappingField[] = [];
    (targets.data?.targets ?? []).forEach((t) => {
      if (have.has(t.target)) return;
      const hit = sampleFields.find((s) => norm(s) === t.target || norm(s).replace(/_/g, "") === t.target.replace(/_/g, ""));
      if (hit) extra.push({ target: t.target, source: hit, type: t.type });
    });
    setSpec({ ...spec, fields: [...spec.fields, ...extra] });
    toast.success(extra.length ? `Suggested ${extra.length} field(s) from the sample — check each one` : "Nothing more could be matched by name");
  };
  const act = async <T,>(fn: () => Promise<T>, done: string): Promise<T | null> => {
    setBusy(true);
    try { const out = await fn(); toast.success(done); await qc.invalidateQueries({ queryKey: ["studio-mappings", entity?.id] }); await qc.invalidateQueries({ queryKey: ["studio-mapping", entity?.id, id] }); return out; }
    catch (e) { toast.error("Refused", { description: e instanceof Error ? e.message : "" }); return null; }
    finally { setBusy(false); }
  };
  const runPreview = async () => {
    try { setPreview(await studioMapApi.preview(spec, v.object_type, sample)); }
    catch (e) { toast.error("Preview refused", { description: e instanceof Error ? e.message : "" }); }
  };

  return (
    <div className="space-y-5">
      <PageHeader eyebrow={`PeopleOps Studio · ${OBJECT_LABEL[v.object_type] ?? v.object_type} mapping`}
        title={<span className="flex flex-wrap items-center gap-3">{v.name} <span className="font-mono text-base text-ink-500">{v.label}</span>
          <Badge variant={v.status === "published" ? "success" : v.status === "draft" ? "warning" : "secondary"}>{v.status}</Badge></span>}
        description={v.status === "published" ? `Published ${v.published_at ? new Date(v.published_at).toLocaleString("en-IN") : ""}. A published version never changes — draft a new one to change it.` : v.status === "retired" ? "Retired: no longer chosen for new runs. Runs that used it keep their reference." : "Draft: edit, preview on sample data, then publish."}
        actions={<div className="flex flex-wrap gap-2">
          <Link href="/studio/mapping" className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-ink-200 px-3 text-sm"><ArrowLeft size={14} /> All</Link>
          {editable ? <button type="button" disabled={busy} onClick={() => void act(() => studioMapApi.update(v.id, { spec, change_reason: reason }), "Draft saved")} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-brand-300 px-3 text-sm font-semibold text-brand-700"><Save size={14} /> Save draft</button> : null}
          {draft && canPublish ? <button type="button" disabled={busy} onClick={() => void act(async () => { await studioMapApi.update(v.id, { spec, change_reason: reason }); return studioMapApi.publish(v.id); }, "Published")} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-brand-600 px-3 text-sm font-semibold text-white"><Send size={14} /> Publish</button> : null}
          {!draft && canWrite ? <button type="button" disabled={busy} onClick={() => void act(() => studioMapApi.newVersion(v.id, `From v${v.version}`), "New draft created").then((n) => n && router.push(`/studio/mapping/${n.id}`))} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-ink-200 px-3 text-sm"><Copy size={14} /> New version</button> : null}
          {v.status === "published" && canPublish ? <button type="button" disabled={busy} onClick={() => { const r = window.prompt("Why retire this version?"); if (r) void act(() => studioMapApi.retire(v.id, r), "Retired"); }} className="h-9 rounded-lg border border-ink-200 px-3 text-sm">Retire</button> : null}
        </div>} />
      <StudioNav />

      <Card><CardContent className="space-y-3 py-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-semibold text-ink-900">1 · Sample data</h2>
          <span className="text-xs text-ink-500">{sample.length ? `${sample.length} record(s) · fields: ${sampleFields.slice(0, 12).join(", ")}${sampleFields.length > 12 ? "…" : ""}` : "No sample yet"}</span>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          <label className="text-xs font-semibold text-ink-700">From a file (CSV or Excel — read as text)
            <input type="file" accept=".csv,.xlsx" className="mt-1 block text-sm" onChange={async (e) => { const f = e.target.files?.[0]; if (f) { setSample(await readSample(f)); setPreview(null); } }} /></label>
          <div className="text-xs font-semibold text-ink-700">From a connection
            <div className="mt-1 flex flex-wrap gap-1">{(connections.data ?? []).flatMap((c) => c.streams.filter((s) => s.object_type === v.object_type).map((s) => (
              <button key={s.id} type="button" className="rounded border border-ink-200 px-2 py-1 font-normal" onClick={async () => {
                try { const r = await studioConnApi.sample(c.id, s.id); setSample(r.records); setPreview(null); } catch (err) { toast.error("Could not fetch a sample", { description: err instanceof Error ? err.message : "" }); }
              }}>{c.name} · {s.name}</button>)))}
              {!(connections.data ?? []).some((c) => c.streams.some((s) => s.object_type === v.object_type)) ? <span className="font-normal text-ink-400">No stream of this kind</span> : null}</div></div>
          <label className="text-xs font-semibold text-ink-700">Or paste JSON records
            <textarea className={cn(FIELD, "mt-1 h-16 font-mono text-xs")} value={json} onChange={(e) => setJson(e.target.value)} placeholder='[{"EmpNo": "00123", "Hired": "15/04/2024"}]' />
            <button type="button" className="mt-1 text-xs underline" onClick={() => { try { const p = JSON.parse(json); setSample(Array.isArray(p) ? p : [p]); setPreview(null); } catch { toast.error("That is not valid JSON"); } }}>Use</button></label>
        </div>
      </CardContent></Card>

      <Card><CardContent className="space-y-3 py-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-semibold text-ink-900">2 · Fields</h2>
          {editable ? <div className="flex gap-2">
            <button type="button" disabled={!sample.length} onClick={suggest} className="rounded-lg border border-ink-200 px-2.5 py-1 text-xs disabled:opacity-40">Suggest from sample</button>
            <button type="button" onClick={addField} className="inline-flex items-center gap-1 rounded-lg border border-brand-300 px-2.5 py-1 text-xs text-brand-700"><Plus size={12} /> Field</button></div> : null}
        </div>
        <p className="text-xs text-ink-500">An empty or missing source value leaves the field absent — never zero — unless you set a default here, where anyone can read it. A value that cannot be read rejects the record, naming the field and the row.</p>
        <datalist id="sample-fields">{sampleFields.map((s) => <option key={s} value={s} />)}</datalist>
        <datalist id="target-fields">{(targets.data?.targets ?? []).map((t) => <option key={t.target} value={t.target} />)}</datalist>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1100px] text-xs">
            <thead className="text-left uppercase tracking-wide text-ink-500"><tr><th className="py-1 pr-2">Product field</th><th className="pr-2">From</th><th className="pr-2">Read as</th><th className="pr-2">Required</th><th className="pr-2">Default</th><th className="pr-2">Format / pad / codes</th><th className="pr-2">Lookup (from=to per line)</th><th className="pr-2">Formula or condition</th><th /></tr></thead>
            <tbody className="divide-y divide-ink-100 align-top">
              {spec.fields.map((f, i) => (
                <tr key={i}>
                  <td className="py-1.5 pr-2"><input list="target-fields" aria-label="Product field" disabled={!editable} className={FIELD} value={f.target} onChange={(e) => setField(i, { target: e.target.value })} placeholder="employee_id or extra.my_field" /></td>
                  <td className="pr-2"><input list="sample-fields" aria-label="Source field" disabled={!editable || !!f.formula || !!f.cases} className={FIELD} value={f.source ?? ""} onChange={(e) => setField(i, { source: e.target.value || undefined })} placeholder="source field (a.b for nested)" /></td>
                  <td className="pr-2"><select aria-label="Read as" disabled={!editable} className={FIELD} value={f.type ?? "text"} onChange={(e) => setField(i, { type: e.target.value })}>
                    {(targets.data?.types ?? ["text"]).filter((t) => t !== "attendance_codes" || v.object_type === "attendance").map((t) => <option key={t} value={t}>{t.replace("_", " ")}</option>)}</select></td>
                  <td className="pr-2 text-center"><input type="checkbox" aria-label="Required" disabled={!editable} checked={!!f.required} onChange={(e) => setField(i, { required: e.target.checked })} /></td>
                  <td className="pr-2"><input aria-label="Default" disabled={!editable} className={FIELD} value={f.default === undefined || f.default === null ? "" : String(f.default)} onChange={(e) => setField(i, { default: e.target.value === "" ? undefined : e.target.value })} placeholder="none" /></td>
                  <td className="pr-2">
                    {f.type === "date" ? <input aria-label="Date formats" disabled={!editable} className={FIELD} value={(f.formats ?? []).join(", ")} onChange={(e) => setField(i, { formats: e.target.value ? e.target.value.split(",").map((x) => x.trim()) : undefined })} placeholder="%d/%m/%Y" /> : null}
                    {f.type === "id" ? <input aria-label="Pad to" disabled={!editable} className={FIELD} value={f.pad_to ?? ""} onChange={(e) => setField(i, { pad_to: e.target.value ? Number(e.target.value) : undefined })} placeholder="pad to width, e.g. 6" /> : null}
                    {f.type === "attendance_codes" ? <textarea aria-label="Attendance codes" disabled={!editable} className={cn(FIELD, "h-16 font-mono")} value={tableToLines(f.codes)} onChange={(e) => setField(i, { codes: linesToTable(e.target.value) })} placeholder={"P=present\nA=lop\nL=paid_leave\nWO=weekly_off\nH=holiday\nHD=half_lop"} /> : null}
                  </td>
                  <td className="pr-2"><textarea aria-label="Lookup" disabled={!editable} className={cn(FIELD, "h-12 font-mono")} value={tableToLines(f.lookup)} onChange={(e) => setField(i, { lookup: e.target.value.trim() ? linesToTable(e.target.value) : undefined })} placeholder="BLR=Karnataka" />
                    {f.lookup ? <select aria-label="If unmatched" disabled={!editable} className={cn(FIELD, "mt-1")} value={f.on_unmatched ?? "reject"} onChange={(e) => setField(i, { on_unmatched: e.target.value as MappingField["on_unmatched"] })}>
                      <option value="reject">No match → reject record</option><option value="keep">No match → keep value</option><option value="blank">No match → leave absent</option></select> : null}</td>
                  <td className="pr-2">
                    <input aria-label="Formula" disabled={!editable || !!f.cases} className={cn(FIELD, "font-mono")} value={f.formula ?? ""} onChange={(e) => setField(i, { formula: e.target.value || undefined, source: e.target.value ? undefined : f.source })} placeholder="BasicMonthly * 12" />
                    {f.cases ? f.cases.map((c, k) => (
                      <div key={k} className="mt-1 flex gap-1">
                        <input aria-label="When field" disabled={!editable} className={FIELD} value={c.when.source} onChange={(e) => setField(i, { cases: f.cases!.map((x, j) => (j === k ? { ...x, when: { ...x.when, source: e.target.value } } : x)) })} placeholder="field" />
                        <input aria-label="Equals" disabled={!editable} className={FIELD} value={String(c.when.value ?? "")} onChange={(e) => setField(i, { cases: f.cases!.map((x, j) => (j === k ? { ...x, when: { ...x.when, value: e.target.value } } : x)) })} placeholder="= value" />
                        <input aria-label="Then" disabled={!editable} className={FIELD} value={String(c.value ?? "")} onChange={(e) => setField(i, { cases: f.cases!.map((x, j) => (j === k ? { ...x, value: e.target.value } : x)) })} placeholder="→ result" />
                      </div>)) : null}
                    {f.cases ? <input aria-label="Otherwise" disabled={!editable} className={cn(FIELD, "mt-1")} value={String(f.else ?? "")} onChange={(e) => setField(i, { else: e.target.value || undefined })} placeholder="otherwise → value" /> : null}
                    {editable && !f.formula ? <button type="button" className="mt-1 text-[11px] underline" onClick={() => setField(i, { cases: [...(f.cases ?? []), { when: { source: "", op: "eq", value: "" }, value: "" }], source: undefined })}>+ condition</button> : null}
                  </td>
                  <td>{editable ? <button type="button" aria-label="Remove field" onClick={() => removeField(i)} className="text-ink-400 hover:text-danger-700"><Trash2 size={14} /></button> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          <label className="text-xs font-semibold text-ink-700">Source record id field (for lineage)<input disabled={!editable} className={cn(FIELD, "mt-1")} value={spec.record_id ?? ""} onChange={(e) => setSpec({ ...spec, record_id: e.target.value || undefined })} placeholder="id" /></label>
          <label className="flex items-center gap-2 self-end pb-2 text-xs"><input type="checkbox" disabled={!editable} checked={!!spec.keep_unmapped} onChange={(e) => setSpec({ ...spec, keep_unmapped: e.target.checked })} /> Keep unmapped fields as client-specific extras</label>
          <label className="text-xs font-semibold text-ink-700">Why this version<input disabled={!editable} className={cn(FIELD, "mt-1")} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
        </div>
      </CardContent></Card>

      <Card><CardContent className="space-y-3 py-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-base font-semibold text-ink-900">3 · Preview</h2>
          <button type="button" disabled={!sample.length} onClick={() => void runPreview()} className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-40"><Eye size={14} /> Preview on the sample</button>
        </div>
        {!preview ? <p className="text-sm text-ink-500">Load sample data, then preview. Nothing is stored.</p> : (
          <>
            <p className="text-sm"><strong>{preview.mapped}</strong> of {preview.rows} record(s) map cleanly; <strong className={preview.rejected ? "text-danger-700" : ""}>{preview.rejected}</strong> would be rejected.{preview.truncated ? " (First 200 shown.)" : ""}</p>
            <div className="max-h-96 overflow-auto rounded-lg border border-ink-200">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-ink-50 text-left uppercase tracking-wide text-ink-500"><tr><th className="px-2 py-1">Row</th><th className="px-2">Result</th><th className="px-2">Output / errors</th></tr></thead>
                <tbody className="divide-y divide-ink-100">
                  {preview.results.map((r) => (
                    <tr key={r.row} className={r.errors.length ? "bg-danger-50/50" : ""}>
                      <td className="px-2 py-1 tabular-nums">{r.row}</td>
                      <td className="px-2">{r.errors.length ? "Rejected" : "Mapped"}{r.defaults_used.length ? <span className="block text-ink-400">default: {r.defaults_used.join(", ")}</span> : null}</td>
                      <td className="px-2 font-mono">{r.errors.length ? r.errors.map((e) => <span key={e.field + e.message} className="block text-danger-700">{e.message}</span>) : JSON.stringify(r.output)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </CardContent></Card>

      {siblings.length > 1 ? (
        <Card><CardContent className="space-y-2 py-5">
          <h2 className="flex items-center gap-2 text-base font-semibold text-ink-900"><GitCompare size={16} /> Compare with another version</h2>
          <select aria-label="Compare with" className={cn(FIELD, "max-w-xs")} value={compareWith} onChange={(e) => setCompareWith(e.target.value)}>
            <option value="">Choose a version</option>{siblings.filter((s) => s.id !== v.id).map((s) => <option key={s.id} value={s.id}>v{s.version} ({s.status})</option>)}</select>
          {compare.data ? (compare.data.changes.length === 0 ? <p className="text-sm text-ink-500">No differences.</p> : (
            <ul className="space-y-1 text-xs">{compare.data.changes.map((c) => (
              <li key={c.target}><strong>{c.target}</strong> — {c.change}{c.before !== undefined ? <span className="block font-mono text-danger-700">− {JSON.stringify(c.before)}</span> : null}{c.after !== undefined ? <span className="block font-mono text-success-700">+ {JSON.stringify(c.after)}</span> : null}</li>))}</ul>)) : null}
        </CardContent></Card>
      ) : null}

      {v.status === "published" && canWrite ? <ImportWithMapping mappingId={v.id} objectType={v.object_type} /> : null}
    </div>
  );
}

function ImportWithMapping({ mappingId, objectType }: { mappingId: string; objectType: string }) {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const [mode, setMode] = useState("upsert");
  const [validate, setValidate] = useState(false);
  const [batch, setBatch] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    if (!file) return;
    setBusy(true);
    const period = `${month}-01`;
    const meta: Record<string, unknown> = { mapping_id: mappingId, batch_id: batch || undefined, source_system: "File upload" };
    if (objectType === "employee_master") Object.assign(meta, { effective_from: period, mode });
    if (objectType === "attendance") Object.assign(meta, { period_month: period, mode });
    if (objectType === "salary_register") Object.assign(meta, { period_month: period, validate });
    try {
      const run = await studioMapApi.importFile(file, meta);
      toast.success("Import queued");
      router.push(`/studio/runs/${run.id}`);
    } catch (e) {
      toast.error("Not imported", { description: e instanceof Error ? e.message : "" });
      setBusy(false);
    }
  };
  return (
    <Card><CardContent className="space-y-3 py-5">
      <h2 className="flex items-center gap-2 text-base font-semibold text-ink-900"><FileUp size={16} /> Import a file with this mapping</h2>
      <p className="text-xs text-ink-500">The same checks, counts, rejections and lineage as the integration API. Every record is accounted for on the run page.</p>
      <div className="grid gap-3 md:grid-cols-5">
        <label className="text-xs font-semibold text-ink-700 md:col-span-2">File<input type="file" accept=".csv,.xlsx" className="mt-1 block text-sm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
        {objectType !== "ctc" ? <label className="text-xs font-semibold text-ink-700">{objectType === "employee_master" ? "Effective from" : "Payroll month"}<input type="month" className={cn(FIELD, "mt-1")} value={month} onChange={(e) => setMonth(e.target.value)} /></label> : null}
        {objectType === "employee_master" || objectType === "attendance" ? <label className="text-xs font-semibold text-ink-700">Mode<select aria-label="Mode" className={cn(FIELD, "mt-1")} value={mode} onChange={(e) => setMode(e.target.value)}><option value="upsert">Upsert</option><option value="replace">Replace</option></select></label> : null}
        <label className="text-xs font-semibold text-ink-700">Batch id<input className={cn(FIELD, "mt-1")} value={batch} onChange={(e) => setBatch(e.target.value)} placeholder="optional" /></label>
      </div>
      {objectType === "salary_register" ? <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={validate} onChange={(e) => setValidate(e.target.checked)} /> Validate the month when stored</label> : null}
      <button type="button" disabled={!file || busy} onClick={() => void go()} className="rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-40">Import</button>
    </CardContent></Card>
  );
}
