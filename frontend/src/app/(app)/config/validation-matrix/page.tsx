"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, FlaskConical, Plus, ShieldCheck } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import { useEntity } from "@/context/EntityContext";
import { apiJson } from "@/lib/api";

type Source = "field" | "component" | "deduction" | "literal";
type Operand = { source: Source; key?: string; value?: string };
type Comparison = { left: Operand; operator: "eq" | "ne" | "gt" | "gte" | "lt" | "lte"; right: Operand; tolerance: string };
type Rule = {
  id: string; rule_key: string; version: number; name: string; category: "custom" | "statutory";
  status: string; effective_from: string; state: string | null; severity: string;
  blocks_signoff: boolean; source_reference: string | null; change_reason: string;
};
type Catalog = {
  built_in: { family: string; examples: string[] }[];
  templates: { key: string; label: string; description: string }[];
  fields: string[]; components: string[]; deductions: string[];
};
type Simulation = { period_month: string; sampled: number; truncated: boolean; findings: { employee_id: string; rule_name: string; reason: string; actual_value: string; expected_value: string }[] };

const input = "w-full rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900 focus:border-brand-500 focus:outline-none";
const initial: Comparison = {
  left: { source: "field", key: "lop_days" },
  operator: "lte",
  right: { source: "literal", value: "0" },
  tolerance: "0",
};
const labels: Record<Comparison["operator"], string> = {
  eq: "Equals", ne: "Does not equal", gt: "Greater than", gte: "At least", lt: "Less than", lte: "At most",
};

function OperandEditor({ label, value, onChange, catalog }: {
  label: string; value: Operand; onChange: (value: Operand) => void; catalog: Catalog;
}) {
  const options = value.source === "field" ? catalog.fields : value.source === "component" ? catalog.components : catalog.deductions;
  return (
    <div className="space-y-1">
      <span className="text-xs font-semibold text-ink-700">{label}</span>
      <div className="grid gap-2 sm:grid-cols-2">
        <select aria-label={`${label} source`} className={input} value={value.source} onChange={(event) => {
          const source = event.target.value as Source;
          onChange(source === "literal" ? { source, value: "" } : { source, key: (source === "field" ? catalog.fields : source === "component" ? catalog.components : catalog.deductions)[0] ?? "" });
        }}>
          <option value="field">Payroll field</option>
          <option value="component">Salary component</option>
          <option value="deduction">Deduction</option>
          <option value="literal">Fixed value</option>
        </select>
        {value.source === "literal" ? (
          <input aria-label={`${label} fixed value`} className={input} value={value.value ?? ""} onChange={(event) => onChange({ source: "literal", value: event.target.value })} placeholder="Amount or text" />
        ) : (
          <select aria-label={`${label} selection`} className={input} value={value.key ?? ""} onChange={(event) => onChange({ source: value.source, key: event.target.value })}>
            {!options.length && <option value="">Configure a component first</option>}
            {options.map((key) => <option key={key} value={key}>{key.replaceAll("_", " ")}</option>)}
          </select>
        )}
      </div>
    </div>
  );
}

function ComparisonEditor({ title, value, onChange, catalog }: {
  title: string; value: Comparison; onChange: (value: Comparison) => void; catalog: Catalog;
}) {
  return (
    <div className="space-y-3 rounded-xl border border-ink-200 bg-ink-50/50 p-3">
      <h3 className="text-sm font-semibold text-ink-900">{title}</h3>
      <div className="grid gap-3 lg:grid-cols-[1fr_11rem_1fr]">
        <OperandEditor label="Check this" value={value.left} onChange={(left) => onChange({ ...value, left })} catalog={catalog} />
        <label className="text-xs font-semibold text-ink-700">Comparison
          <select className={`mt-1 ${input}`} value={value.operator} onChange={(event) => onChange({ ...value, operator: event.target.value as Comparison["operator"] })}>
            {Object.entries(labels).map(([key, text]) => <option key={key} value={key}>{text}</option>)}
          </select>
        </label>
        <OperandEditor label="Against this" value={value.right} onChange={(right) => onChange({ ...value, right })} catalog={catalog} />
      </div>
      <label className="block max-w-[11rem] text-xs font-semibold text-ink-700">Allowed difference
        <input className={`mt-1 ${input}`} inputMode="decimal" value={value.tolerance} onChange={(event) => onChange({ ...value, tolerance: event.target.value })} />
      </label>
    </div>
  );
}

export default function ValidationMatrixPage() {
  const { entity, role, activeRole, canManageGroup } = useEntity();
  const qc = useQueryClient();
  const [key, setKey] = useState("CUST-");
  const [name, setName] = useState("");
  const [category, setCategory] = useState<"custom" | "statutory">("custom");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [state, setState] = useState("");
  const [source, setSource] = useState("");
  const [reason, setReason] = useState("");
  const [severity, setSeverity] = useState<"INFO" | "WARNING" | "CRITICAL">("WARNING");
  const [blocks, setBlocks] = useState(false);
  const [fix, setFix] = useState("");
  const [assertion, setAssertion] = useState<Comparison>(initial);
  const [conditions, setConditions] = useState<Comparison[]>([]);
  const [conditionMode, setConditionMode] = useState<"all" | "any">("all");
  const [period, setPeriod] = useState("");
  const [simulation, setSimulation] = useState<Simulation | null>(null);
  const [activeTest, setActiveTest] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const catalog = useQuery({ queryKey: ["matrix-catalog", entity?.id], queryFn: () => apiJson<Catalog>("/api/validation-matrix/catalog"), enabled: !!entity });
  const rules = useQuery({ queryKey: ["matrix-rules", entity?.id], queryFn: () => apiJson<Rule[]>("/api/validation-matrix"), enabled: !!entity });
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["matrix-rules", entity?.id] }); };
  const create = useMutation({
    mutationFn: () => apiJson<Rule>("/api/validation-matrix", { method: "POST", body: JSON.stringify({
      rule_key: key.trim().toUpperCase(), name: name.trim(), category, effective_from: effectiveFrom,
      state: state.trim() || null, conditions, condition_mode: conditionMode, assertion, severity, blocks_signoff: blocks,
      suggested_fix: fix.trim() || null, source_reference: source.trim() || null, change_reason: reason.trim(),
    }) }),
    onSuccess: () => { setError(null); setName(""); setReason(""); refresh(); },
    onError: (e: Error) => setError(e.message),
  });
  const action = useMutation({
    mutationFn: ({ id, verb }: { id: string; verb: "submit" | "publish" }) =>
      apiJson(`/api/validation-matrix/${id}/${verb}`, { method: "POST" }),
    onSuccess: () => { setError(null); refresh(); },
    onError: (e: Error) => setError(e.message),
  });
  const simulate = useMutation({
    mutationFn: (id: string) => apiJson<Simulation>(`/api/validation-matrix/${id}/simulate`, {
      method: "POST", body: JSON.stringify({ period_month: `${period}-01` }),
    }),
    onSuccess: (result) => { setError(null); setSimulation(result); },
    onError: (e: Error) => setError(e.message),
  });
  const canDraft = activeRole === "owner" || activeRole === "manager";
  const catalogData = catalog.data;

  return (
    <div className="space-y-6">
      <PageHeader title="Validation decision matrix" description="Built-in checks stay active. Add company rules as drafts, test them on a saved register, and publish an approved version for future validation runs." />
      {error && <AlertBanner variant="error" title="Rule action failed">{error}</AlertBanner>}
      {catalog.isError || rules.isError ? <AlertBanner variant="error" title="Could not load rules">Retry this page or check the API connection.</AlertBanner> : null}
      <div className="grid gap-3 md:grid-cols-3">
        {(catalogData?.built_in ?? []).map((group) => <Card key={group.family}><CardContent className="py-4"><h2 className="text-sm font-semibold text-ink-900">{group.family}</h2><p className="mt-1 text-xs leading-relaxed text-ink-500">{group.examples.join(" · ")}</p></CardContent></Card>)}
      </div>
      <p className="text-xs text-ink-500">Built-in statutory checks use their existing configuration. Matrix rules add a versioned company policy or a reviewed statutory check; they do not replace official PT, LWF, PF, ESIC or minimum wage tables.</p>

      {canDraft && catalogData && (
        <Card><CardContent className="space-y-4 py-5">
          <h2 className="flex items-center gap-2 text-base font-semibold text-ink-900"><Plus size={17} /> Create a draft</h2>
          <p className="text-xs text-ink-500">Choose mapped fields or salary components. Missing inputs become findings; a rule never silently passes when it cannot be evaluated.</p>
          <form onSubmit={(event) => { event.preventDefault(); create.mutate(); }} className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <label className="text-xs font-semibold text-ink-700">Rule key<input required className={`mt-1 ${input}`} value={key} onChange={(event) => setKey(event.target.value.toUpperCase())} placeholder="CUST-LOP-01" /></label>
              <label className="text-xs font-semibold text-ink-700">Rule name<input required className={`mt-1 ${input}`} value={name} onChange={(event) => setName(event.target.value)} placeholder="LOP threshold" /></label>
              <label className="text-xs font-semibold text-ink-700">Type<select className={`mt-1 ${input}`} value={category} onChange={(event) => { const value = event.target.value as typeof category; setCategory(value); setKey(value === "statutory" ? "STATX-" : "CUST-"); }}><option value="custom">Company policy</option><option value="statutory">Statutory</option></select></label>
              <label className="text-xs font-semibold text-ink-700">Effective from<input required type="date" className={`mt-1 ${input}`} value={effectiveFrom} onChange={(event) => setEffectiveFrom(event.target.value)} /></label>
              <label className="text-xs font-semibold text-ink-700">Work state (optional)<input className={`mt-1 ${input}`} value={state} onChange={(event) => setState(event.target.value)} placeholder="Applies to all states if blank" /></label>
              <label className="text-xs font-semibold text-ink-700">Severity<select className={`mt-1 ${input}`} value={severity} onChange={(event) => setSeverity(event.target.value as typeof severity)}><option>INFO</option><option>WARNING</option><option>CRITICAL</option></select></label>
            </div>
            <ComparisonEditor title="Expected check" value={assertion} onChange={setAssertion} catalog={catalogData} />
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-xs font-semibold text-ink-700">Apply rule when</span>
              <select aria-label="Condition matching" className={`max-w-48 ${input}`} value={conditionMode} onChange={(event) => setConditionMode(event.target.value as "all" | "any")}><option value="all">All conditions match</option><option value="any">Any condition matches</option></select>
              <button type="button" disabled={conditions.length >= 5} onClick={() => setConditions([...conditions, { ...initial }])} className="rounded-lg border border-brand-300 px-3 py-1.5 text-xs font-semibold text-brand-700 disabled:opacity-50">Add condition</button>
            </div>
            {conditions.map((item, index) => <div key={index} className="space-y-2"><ComparisonEditor title={`Condition ${index + 1}`} value={item} onChange={(next) => setConditions(conditions.map((existing, i) => i === index ? next : existing))} catalog={catalogData} /><button type="button" onClick={() => setConditions(conditions.filter((_, i) => i !== index))} className="text-xs font-semibold text-ink-600">Remove condition</button></div>)}
            <label className="flex items-center gap-2 text-xs font-semibold text-ink-700"><input type="checkbox" checked={blocks} onChange={(event) => setBlocks(event.target.checked)} /> Block sign-off when this check fails</label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="text-xs font-semibold text-ink-700">Source notification or policy reference{category === "statutory" ? " *" : ""}<input required={category === "statutory"} className={`mt-1 ${input}`} value={source} onChange={(event) => setSource(event.target.value)} placeholder="Official URL or policy identifier" /></label>
              <label className="text-xs font-semibold text-ink-700">Suggested resolution<input className={`mt-1 ${input}`} value={fix} onChange={(event) => setFix(event.target.value)} placeholder="What HR should review" /></label>
            </div>
            <label className="block text-xs font-semibold text-ink-700">Why this version is needed *<textarea required minLength={8} className={`mt-1 ${input}`} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
            <button type="submit" disabled={create.isPending} className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">Save draft</button>
          </form>
        </CardContent></Card>
      )}

      <Card><CardContent className="space-y-4 py-5">
        <h2 className="text-base font-semibold text-ink-900">Company rule versions</h2>
        <label className="block max-w-xs text-xs font-semibold text-ink-700">Register month for simulation<input type="month" className={`mt-1 ${input}`} value={period} onChange={(event) => setPeriod(event.target.value)} /></label>
        {(rules.data ?? []).length === 0 && <p className="text-sm text-ink-500">No custom rules yet. Built-in validation still runs.</p>}
        <div className="divide-y divide-ink-200">
          {(rules.data ?? []).map((rule) => (
            <div key={rule.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
              <div>
                <p className="text-sm font-semibold text-ink-900">{rule.name} <span className="text-xs font-normal text-ink-500">· {rule.rule_key} v{rule.version}</span></p>
                <p className="text-xs text-ink-500">{rule.category} · {rule.status} · from {rule.effective_from}{rule.state ? ` · ${rule.state}` : ""}{rule.blocks_signoff ? " · blocks sign-off" : ""}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                {canDraft && <button type="button" disabled={!period || simulate.isPending} onClick={() => { setActiveTest(rule.id); setSimulation(null); simulate.mutate(rule.id); }} className="inline-flex items-center gap-1 rounded-lg border border-ink-200 px-3 py-1.5 text-xs font-semibold text-ink-700 disabled:opacity-50"><FlaskConical size={13} /> Simulate</button>}
                {canDraft && rule.status === "draft" && <button type="button" disabled={action.isPending} onClick={() => action.mutate({ id: rule.id, verb: "submit" })} className="rounded-lg border border-brand-300 px-3 py-1.5 text-xs font-semibold text-brand-700">Submit</button>}
                {rule.status === "pending" && (rule.category === "custom" ? canDraft : canManageGroup && role === "owner") && <button type="button" disabled={action.isPending} onClick={() => action.mutate({ id: rule.id, verb: "publish" })} className="inline-flex items-center gap-1 rounded-lg bg-brand-600 px-3 py-1.5 text-xs font-semibold text-white"><ShieldCheck size={13} /> Publish</button>}
              </div>
              {activeTest === rule.id && simulation && <div className="w-full rounded-lg bg-brand-50 p-3 text-xs text-ink-700"><p className="font-semibold">{simulation.findings.length} issues in {simulation.sampled} sampled rows {simulation.truncated ? "· sample limit reached" : ""}</p><div className="mt-2 max-h-40 space-y-1 overflow-auto">{simulation.findings.slice(0, 20).map((finding, index) => <p key={`${finding.employee_id}-${index}`} className="flex gap-2"><AlertTriangle size={13} className="shrink-0 text-warning-700" /> {finding.employee_id}: {finding.reason}</p>)}{simulation.findings.length === 0 && <p className="flex gap-1"><CheckCircle2 size={13} /> No issues in this sample.</p>}</div></div>}
            </div>
          ))}
        </div>
      </CardContent></Card>
    </div>
  );
}
