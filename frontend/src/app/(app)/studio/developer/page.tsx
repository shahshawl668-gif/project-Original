"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { Calculator, Filter, ListTree, Lock } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import { StudioNav } from "@/components/studio/StudioNav";
import { studioDevApi, type FormulaResult, type WorkflowCondition } from "@/lib/studio";
import { cn } from "@/lib/utils";

const FIELD =
  "w-full rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900";

function parseRows(text: string): unknown[] | null {
  try {
    const v = JSON.parse(text);
    return Array.isArray(v) ? v : [v];
  } catch {
    toast.error("The sample is not valid JSON");
    return null;
  }
}

export default function DeveloperPage() {
  const { entity } = useEntity();
  const ref = useQuery({ queryKey: ["studio-dev-ref", entity?.id], queryFn: studioDevApi.reference, enabled: !!entity });
  return (
    <div className="space-y-5">
      <PageHeader eyebrow="PeopleOps Studio" title="Developer workspace"
        description="Test formulas, conditions and lookups on sample rows before they go into a mapping, a rule or a workflow. The same evaluators the product runs; nothing is stored." />
      <StudioNav />
      <FormulaTester />
      <div className="grid gap-4 lg:grid-cols-2">
        <ConditionTester />
        <LookupTester />
      </div>
      {ref.data ? (
        <Card><CardContent className="grid gap-4 py-5 md:grid-cols-2">
          <div className="text-sm">
            <h2 className="mb-2 text-base font-semibold text-ink-900">What a formula may use</h2>
            <ul className="space-y-0.5 text-xs">{Object.entries(ref.data.functions).map(([k, v]) => <li key={k}><code>{k}()</code> — {v}</li>)}</ul>
            <p className="mt-2 text-xs"><strong>Operators:</strong> {ref.data.operators.join("  ")}</p>
            <p className="mt-2 text-xs"><strong>Never:</strong> {ref.data.not_allowed.join("; ")}.</p>
            <p className="mt-2 text-xs text-ink-500">{ref.data.variables} Up to {ref.data.max_length} characters.</p>
          </div>
          <div className="rounded-xl border border-ink-200 bg-ink-50/60 p-4 text-sm" data-testid="scripting">
            <h2 className="mb-2 flex items-center gap-2 text-base font-semibold text-ink-900"><Lock size={16} /> Scripting — disabled</h2>
            <p className="text-xs">{ref.data.scripting.reason}</p>
            <p className="mt-2 text-xs font-semibold">It would need, first:</p>
            <ul className="list-disc pl-5 text-xs">{ref.data.scripting.requires.map((r) => <li key={r}>{r}</li>)}</ul>
            <p className="mt-2 text-xs text-ink-500">{ref.data.scripting.instead}</p>
          </div>
        </CardContent></Card>
      ) : null}
    </div>
  );
}

function FormulaTester() {
  const [expression, setExpression] = useState("min(pf_wage, 15000) * 0.12");
  const [sample, setSample] = useState('[{"employee_id": "00123", "pf_wage": "18,000"}, {"employee_id": "00124", "pf_wage": ""}]');
  const [out, setOut] = useState<FormulaResult | null>(null);
  const run = async () => {
    const rows = parseRows(sample);
    if (!rows) return;
    try { setOut(await studioDevApi.formula(expression, rows)); } catch (e) { toast.error(e instanceof Error ? e.message : "Refused"); }
  };
  return (
    <Card><CardContent className="space-y-3 py-5">
      <h2 className="flex items-center gap-2 text-base font-semibold text-ink-900"><Calculator size={16} /> Formula</h2>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="text-xs font-semibold text-ink-700">Expression<input aria-label="Expression" className={cn(FIELD, "mt-1 font-mono")} value={expression} onChange={(e) => setExpression(e.target.value)} /></label>
        <label className="text-xs font-semibold text-ink-700">Sample rows (JSON)<textarea aria-label="Formula sample" className={cn(FIELD, "mt-1 h-20 font-mono text-xs")} value={sample} onChange={(e) => setSample(e.target.value)} /></label>
      </div>
      <button type="button" onClick={() => void run()} className="rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-semibold text-white">Test</button>
      {out ? (
        <div className="space-y-2 text-sm" data-testid="formula-result">
          {out.ok ? (
            <p><strong>In words:</strong> {out.in_words}. <span className="text-ink-500">Reads {out.variables?.join(", ") || "nothing"}{out.functions?.length ? `; calls ${out.functions.join(", ")}` : ""}.</span></p>
          ) : <AlertBanner variant="error" title="Refused">{out.error}</AlertBanner>}
          {out.results.length ? (
            <table className="w-full text-xs"><thead className="text-left uppercase text-ink-500"><tr><th className="py-1">Row</th><th>Result</th><th>Read</th></tr></thead>
              <tbody className="divide-y divide-ink-100">{out.results.map((r) => (
                <tr key={r.row} className={r.error ? "text-danger-700" : ""}><td className="py-1">{r.row}</td><td className="font-mono">{r.error ?? r.value}</td>
                  <td className="font-mono">{r.inputs ? JSON.stringify(r.inputs) : ""}</td></tr>))}</tbody></table>
          ) : null}
        </div>
      ) : null}
    </CardContent></Card>
  );
}

function ConditionTester() {
  const [conds, setConds] = useState<WorkflowCondition[]>([{ field: "data.counts.rejected", op: "gt", value: "0" }]);
  const [sample, setSample] = useState('[{"data": {"counts": {"rejected": 3}}}, {"data": {"counts": {"rejected": 0}}}]');
  const [out, setOut] = useState<Awaited<ReturnType<typeof studioDevApi.conditions>> | null>(null);
  const run = async () => {
    const rows = parseRows(sample);
    if (!rows) return;
    try { setOut(await studioDevApi.conditions(conds, rows)); } catch (e) { toast.error(e instanceof Error ? e.message : "Refused"); }
  };
  return (
    <Card><CardContent className="space-y-3 py-5">
      <h2 className="flex items-center gap-2 text-base font-semibold text-ink-900"><Filter size={16} /> Conditions</h2>
      {conds.map((c, i) => (
        <div key={i} className="grid grid-cols-[1fr_6rem_1fr] gap-2">
          <input aria-label="Condition field" className={FIELD} value={c.field} onChange={(e) => setConds(conds.map((x, j) => (j === i ? { ...x, field: e.target.value } : x)))} />
          <select aria-label="Condition operator" className={FIELD} value={c.op} onChange={(e) => setConds(conds.map((x, j) => (j === i ? { ...x, op: e.target.value } : x)))}>
            {["eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "present", "absent"].map((o) => <option key={o}>{o}</option>)}</select>
          <input aria-label="Condition value" className={FIELD} value={String(c.value ?? "")} onChange={(e) => setConds(conds.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} />
        </div>
      ))}
      <button type="button" className="text-xs underline" onClick={() => setConds([...conds, { field: "data.status", op: "eq", value: "" }])}>+ condition</button>
      <textarea aria-label="Condition sample" className={cn(FIELD, "h-16 font-mono text-xs")} value={sample} onChange={(e) => setSample(e.target.value)} />
      <button type="button" onClick={() => void run()} className="rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-semibold text-white">Test</button>
      {out ? (out.ok ? (
        <ul className="text-xs" data-testid="condition-result">{out.results.map((r) => (
          <li key={r.row}>Row {r.row}: <strong>{r.holds ? "matches" : "does not match"}</strong> — {r.conditions.map((c) => `${c.field} is ${JSON.stringify(c.actual)}`).join("; ")}</li>))}</ul>
      ) : <AlertBanner variant="error" title="Refused">{out.error}</AlertBanner>) : null}
    </CardContent></Card>
  );
}

function LookupTester() {
  const [table, setTable] = useState("BLR=Karnataka\nMUM=Maharashtra");
  const [values, setValues] = useState("BLR, MUM, XYZ");
  const [policy, setPolicy] = useState("reject");
  const [out, setOut] = useState<Awaited<ReturnType<typeof studioDevApi.lookup>> | null>(null);
  const run = async () => {
    const t: Record<string, string> = {};
    table.split("\n").forEach((l) => { const i = l.indexOf("="); if (i > 0) t[l.slice(0, i).trim()] = l.slice(i + 1).trim(); });
    try { setOut(await studioDevApi.lookup(t, values.split(",").map((v) => v.trim()), policy)); } catch (e) { toast.error(e instanceof Error ? e.message : "Refused"); }
  };
  return (
    <Card><CardContent className="space-y-3 py-5">
      <h2 className="flex items-center gap-2 text-base font-semibold text-ink-900"><ListTree size={16} /> Lookup</h2>
      <textarea aria-label="Lookup table" className={cn(FIELD, "h-16 font-mono text-xs")} value={table} onChange={(e) => setTable(e.target.value)} />
      <div className="grid grid-cols-[1fr_12rem] gap-2">
        <input aria-label="Lookup values" className={FIELD} value={values} onChange={(e) => setValues(e.target.value)} />
        <select aria-label="If unmatched" className={FIELD} value={policy} onChange={(e) => setPolicy(e.target.value)}>
          <option value="reject">No match → reject</option><option value="keep">No match → keep</option><option value="blank">No match → absent</option></select>
      </div>
      <button type="button" onClick={() => void run()} className="rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-semibold text-white">Test</button>
      {out ? (out.ok ? (
        <ul className="text-xs" data-testid="lookup-result">{out.results.map((r) => (
          <li key={r.row} className={r.error ? "text-danger-700" : ""}>{String(r.value)} → {r.error ?? (r.result === null || r.result === undefined ? "absent" : String(r.result))}{!r.error && r.matched === false ? " (kept: no match)" : ""}</li>))}</ul>
      ) : <AlertBanner variant="error" title="Refused">{out.error}</AlertBanner>) : null}
    </CardContent></Card>
  );
}
