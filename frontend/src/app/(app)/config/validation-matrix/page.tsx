"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, CheckCircle2, Copy, Download, FlaskConical, GitCompare, History, Plus, ShieldCheck, Upload,
} from "lucide-react";
import { toast } from "sonner";

import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import { BLANK, ComparisonEditor, GroupEditor, INPUT } from "@/components/validation/ConditionBuilder";
import { RulePacks } from "@/components/validation/RulePacks";
import { useEntity } from "@/context/EntityContext";
import { apiBlob, apiJson } from "@/lib/api";
import {
  ON_MISSING_LABEL, describeComparison, describeCondition, matrixApi,
  type Catalog, type Comparison, type CopyResult, type Group, type Impact, type ImportPreview, type OnMissing,
  type Rule, type RuleDraft, type RuleTemplate,
} from "@/lib/matrix";
import { cn } from "@/lib/utils";

type Preference = { rule_id: string; suppressed: boolean };

const STATUS_TONE: Record<Rule["status"], string> = {
  draft: "bg-ink-100 text-ink-700",
  pending: "bg-warning-100 text-warning-800",
  published: "bg-success-100 text-success-800",
  retired: "bg-ink-200 text-ink-600",
};

/**
 * The validation decision matrix.
 *
 * Built-in checks (as packs and one by one), and the company's own rules:
 * drafted in a Basic or Advanced editor, tested on a whole saved month,
 * approved, versioned, compared, rolled back, retired, imported and copied.
 * A rule is data the server evaluates — nothing here runs anyone's code.
 */
export default function ValidationMatrixPage() {
  const { entity, entities, role, activeRole, canManageGroup } = useEntity();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const canDraft = activeRole === "owner" || activeRole === "manager";

  const catalog = useQuery({ queryKey: ["matrix-catalog", entity?.id], queryFn: matrixApi.catalog, enabled: !!entity });
  const templates = useQuery({ queryKey: ["matrix-templates", entity?.id], queryFn: matrixApi.templates, enabled: !!entity });
  const rules = useQuery({ queryKey: ["matrix-rules", entity?.id], queryFn: matrixApi.rules, enabled: !!entity });
  const conflicts = useQuery({ queryKey: ["matrix-conflicts", entity?.id], queryFn: matrixApi.conflicts, enabled: !!entity });
  const preferences = useQuery({ queryKey: ["matrix-preferences", entity?.id], queryFn: () => apiJson<Preference[]>("/api/rule-preferences"), enabled: !!entity });
  const toggle = useMutation({
    mutationFn: ({ rule_id, enabled }: { rule_id: string; enabled: boolean }) => apiJson("/api/rule-preferences", {
      method: "PUT", body: JSON.stringify({ rule_id, suppressed: !enabled }),
    }),
    onSuccess: () => { setError(null); void qc.invalidateQueries({ queryKey: ["matrix-preferences", entity?.id] }); },
    onError: (e: Error) => setError(e.message),
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["matrix-rules", entity?.id] });
    void qc.invalidateQueries({ queryKey: ["matrix-conflicts", entity?.id] });
  };

  const catalogData = catalog.data;
  const disabledRules = new Set((preferences.data ?? []).filter((p) => p.suppressed).map((p) => p.rule_id));
  const displayedRules = (catalogData?.built_in_rules ?? []).filter((item) =>
    `${item.rule_id} ${item.name} ${item.family}`.toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="space-y-6">
      <PageHeader title="Validation decision matrix" description="Built-in checks, grouped into packs, and your company's own rules — drafted, tested on a real month, approved and versioned. Rules are data the server evaluates; nothing here runs your code." />
      {error && <AlertBanner variant="error" title="Rule action failed">{error}</AlertBanner>}
      {catalog.isError || rules.isError ? <AlertBanner variant="error" title="Could not load rules">Retry this page or check the API connection.</AlertBanner> : null}

      <RulePacks entityId={entity?.id} canChange={canDraft} />

      <Card><CardContent className="space-y-3 py-5">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-base font-semibold text-ink-900 dark:text-white">Individual built-in checks</h2><p className="text-xs text-ink-500">{catalogData?.built_in_rules.length ?? 0} implemented checks · enabled by default. A disabled check reports “Disabled” in every run; it does not change statutory calculations.</p></div><input aria-label="Search validation checks" className={`max-w-xs ${INPUT}`} value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search rule, topic or ID" /></div>
        {preferences.isError && <AlertBanner variant="error" title="Could not load rule settings">Refresh before changing a check.</AlertBanner>}
        <div className="max-h-[20rem] divide-y divide-ink-200 overflow-auto dark:divide-white/10">
          {displayedRules.map((item) => <div key={item.rule_id} className="flex items-center justify-between gap-3 py-2"><div><p className="text-sm font-semibold text-ink-900 dark:text-white">{item.name} <span className="font-mono text-xs font-normal text-ink-500">{item.rule_id}</span></p><p className="text-xs text-ink-500">{item.family}</p></div><label className="flex shrink-0 items-center gap-2 text-xs font-semibold text-ink-700"><input type="checkbox" checked={!disabledRules.has(item.rule_id)} disabled={!canDraft || preferences.isPending || preferences.isError || toggle.isPending} onChange={(event) => toggle.mutate({ rule_id: item.rule_id, enabled: event.target.checked })} /> Enabled</label></div>)}
          {catalogData && displayedRules.length === 0 && <p className="py-4 text-sm text-ink-500">No matching checks.</p>}
        </div>
      </CardContent></Card>

      {canDraft && catalogData ? (
        <RuleEditor catalog={catalogData} templates={templates.data ?? []} onCreated={() => { setError(null); refresh(); }} />
      ) : null}

      {(conflicts.data ?? []).length ? (
        <AlertBanner variant="warning" title={`${conflicts.data!.length} conflict(s) between company rules`}>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {conflicts.data!.map((c, i) => <li key={i}><strong>{c.kind.replace("_", " ")}:</strong> {c.message}</li>)}
          </ul>
          <p className="mt-1 text-xs">A contradiction or broken reference stops the version involved from being published.</p>
        </AlertBanner>
      ) : null}

      <RuleVersions
        rules={rules.data ?? []} canDraft={canDraft}
        canPublishStatutory={canManageGroup && role === "owner"}
        disabledRules={disabledRules}
        otherCompanies={entities.filter((e) => e.id !== entity?.id)}
        onChanged={refresh}
      />

      {canDraft ? <ImportCard onChanged={refresh} /> : null}
    </div>
  );
}

// ─── Drafting ────────────────────────────────────────────────────────────────

function RuleEditor({ catalog, templates, onCreated }: {
  catalog: Catalog; templates: RuleTemplate[]; onCreated: () => void;
}) {
  const [mode, setMode] = useState<"basic" | "advanced">("basic");
  const [key, setKey] = useState("CUST-");
  const [name, setName] = useState("");
  const [category, setCategory] = useState<"custom" | "statutory">("custom");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [effectiveTo, setEffectiveTo] = useState("");
  const [state, setState] = useState("");
  const [source, setSource] = useState("");
  const [reason, setReason] = useState("");
  const [severity, setSeverity] = useState("WARNING");
  const [blocks, setBlocks] = useState(false);
  const [fix, setFix] = useState("");
  const [assertion, setAssertion] = useState<Comparison>(BLANK);
  const [conditions, setConditions] = useState<Comparison[]>([]);
  const [conditionMode, setConditionMode] = useState<"all" | "any">("all");
  const [group, setGroup] = useState<Group | null>(null);
  const [applies, setApplies] = useState<{ dim: string; values: string }[]>([]);
  const [onMissing, setOnMissing] = useState<OnMissing>("cannot_validate");
  const [err, setErr] = useState<string | null>(null);

  const applyTemplate = (t: RuleTemplate) => {
    const r = t.rule;
    setName(r.name ?? t.label);
    setSeverity(r.severity ?? "WARNING");
    setAssertion(r.assertion);
    setFix(r.suggested_fix ?? "");
    setOnMissing((r.on_missing as OnMissing) ?? "cannot_validate");
    setConditions([]);
    setGroup(r.condition_group ?? null);
    setMode(r.editor_mode === "advanced" || r.condition_group ? "advanced" : "basic");
    setKey(`CUST-${t.key.toUpperCase().replaceAll("_", "-").slice(0, 26)}`);
  };

  const create = useMutation({
    mutationFn: () => {
      const draft: RuleDraft = {
        rule_key: key.trim().toUpperCase(), name: name.trim(), category, effective_from: effectiveFrom,
        effective_to: effectiveTo || null, state: state.trim() || null, assertion, severity, blocks_signoff: blocks,
        suggested_fix: fix.trim() || null, source_reference: source.trim() || null, change_reason: reason.trim(),
        on_missing: onMissing, editor_mode: mode,
        applies_to: applies.length
          ? Object.fromEntries(applies.filter((a) => a.values.trim()).map((a) => [a.dim, a.values.split("|").map((v) => v.trim()).filter(Boolean)]))
          : null,
      };
      if (mode === "advanced") draft.condition_group = group;
      else if (conditions.length) { draft.conditions = conditions; draft.condition_mode = conditionMode; }
      return matrixApi.create(draft);
    },
    onSuccess: (rule) => {
      setErr(null); setName(""); setReason("");
      toast.success(`Drafted ${rule.rule_key} v${rule.version}`, { description: "Test it on a month, then submit it for approval." });
      onCreated();
    },
    onError: (e: Error) => setErr(e.message),
  });

  return (
    <Card><CardContent className="space-y-4 py-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-base font-semibold text-ink-900 dark:text-white"><Plus size={17} /> Draft a company rule</h2>
        <div className="inline-flex rounded-lg border border-ink-200 p-0.5 text-xs font-semibold" role="tablist" aria-label="Editor mode">
          {(["basic", "advanced"] as const).map((m) => (
            <button key={m} type="button" role="tab" aria-selected={mode === m} onClick={() => setMode(m)}
              className={cn("rounded-md px-3 py-1.5", mode === m ? "bg-ink-900 text-white dark:bg-white dark:text-ink-900" : "text-ink-600")}>
              {m === "basic" ? "Basic" : "Advanced"}
            </button>
          ))}
        </div>
      </div>
      <p className="text-xs text-ink-500">
        {mode === "basic"
          ? "Compare a field, component or deduction with a value or another field, optionally only when some conditions hold."
          : "Nested AND/OR groups, calculations, last month's values, the employee master, narrowing by department or other dimensions, and what to do when an input is missing."}
      </p>
      {templates.length ? (
        <div className="space-y-2 rounded-xl border border-brand-100 bg-brand-50 p-3 dark:border-brand-500/20 dark:bg-brand-500/5">
          <p className="text-xs font-semibold text-ink-800 dark:text-ink-100">Start from a template</p>
          <div className="flex flex-wrap gap-2">
            {templates.map((t) => (
              <button key={t.key} type="button" disabled={!t.available} onClick={() => applyTemplate(t)}
                title={t.available ? t.label : `Needs the component(s): ${t.missing_components.join(", ")}`}
                className="rounded-lg border border-brand-200 bg-white px-2 py-1 text-xs font-semibold text-brand-700 disabled:opacity-40 dark:bg-transparent">
                {t.label}
              </button>
            ))}
          </div>
          <p className="text-xs text-ink-500">Templates are starting points for your own policy, not statements of law. Review, test on a month, then publish.</p>
        </div>
      ) : null}
      {err ? <AlertBanner variant="error" title="Not drafted">{err}</AlertBanner> : null}
      <form onSubmit={(e) => { e.preventDefault(); create.mutate(); }} className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <label className="text-xs font-semibold text-ink-700">Rule key<input required className={`mt-1 ${INPUT}`} value={key} onChange={(e) => setKey(e.target.value.toUpperCase())} placeholder="CUST-LOP-01" /></label>
          <label className="text-xs font-semibold text-ink-700">Rule name<input required className={`mt-1 ${INPUT}`} value={name} onChange={(e) => setName(e.target.value)} placeholder="LOP threshold" /></label>
          <label className="text-xs font-semibold text-ink-700">Type<select className={`mt-1 ${INPUT}`} value={category} onChange={(e) => { const v = e.target.value as typeof category; setCategory(v); setKey(v === "statutory" ? "STATX-" : "CUST-"); }}><option value="custom">Company policy</option><option value="statutory">Statutory</option></select></label>
          <label className="text-xs font-semibold text-ink-700">Effective from<input required type="date" className={`mt-1 ${INPUT}`} value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} /></label>
          <label className="text-xs font-semibold text-ink-700">Effective to (optional)<input type="date" className={`mt-1 ${INPUT}`} value={effectiveTo} onChange={(e) => setEffectiveTo(e.target.value)} /></label>
          <label className="text-xs font-semibold text-ink-700">Severity<select className={`mt-1 ${INPUT}`} value={severity} onChange={(e) => setSeverity(e.target.value)}><option>INFO</option><option>WARNING</option><option>CRITICAL</option></select></label>
          <label className="text-xs font-semibold text-ink-700">Work state (optional)<input className={`mt-1 ${INPUT}`} value={state} onChange={(e) => setState(e.target.value)} placeholder="All states if blank" /></label>
        </div>

        <ComparisonEditor title="Expected check" value={assertion} onChange={setAssertion} catalog={catalog} advanced={mode === "advanced"} />

        {mode === "basic" ? (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-xs font-semibold text-ink-700">Apply rule when</span>
              <select aria-label="Condition matching" className={`max-w-48 ${INPUT}`} value={conditionMode} onChange={(e) => setConditionMode(e.target.value as "all" | "any")}><option value="all">All conditions match</option><option value="any">Any condition matches</option></select>
              <button type="button" disabled={conditions.length >= 5} onClick={() => setConditions([...conditions, { ...BLANK }])} className="rounded-lg border border-brand-300 px-3 py-1.5 text-xs font-semibold text-brand-700 disabled:opacity-50">Add condition</button>
            </div>
            {conditions.map((item, index) => (
              <ComparisonEditor key={index} title={`Condition ${index + 1}`} value={item} catalog={catalog} advanced={false}
                onChange={(next) => setConditions(conditions.map((c, i) => (i === index ? next : c)))}
                onRemove={() => setConditions(conditions.filter((_, i) => i !== index))} />
            ))}
          </>
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-xs font-semibold text-ink-700">Apply rule when</span>
              {group ? (
                <button type="button" onClick={() => setGroup(null)} className="text-xs font-semibold text-ink-600">Always apply (remove conditions)</button>
              ) : (
                <button type="button" onClick={() => setGroup({ mode: "all", negate: false, items: [{ ...BLANK }] })} className="rounded-lg border border-brand-300 px-3 py-1.5 text-xs font-semibold text-brand-700">Add a condition group</button>
              )}
            </div>
            {group ? <GroupEditor value={group} onChange={setGroup} catalog={catalog} /> : <p className="text-xs text-ink-500">Applies to every employee in scope.</p>}
            <div className="space-y-2 rounded-xl border border-ink-200 p-3 dark:border-white/10">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-ink-700">Only for (optional)</span>
                <button type="button" onClick={() => setApplies([...applies, { dim: catalog.dimensions[0], values: "" }])} className="text-xs font-semibold text-brand-700">Add a dimension</button>
              </div>
              {applies.map((a, i) => (
                <div key={i} className="grid gap-2 sm:grid-cols-[12rem_1fr_auto]">
                  <select aria-label="Dimension" className={INPUT} value={a.dim} onChange={(e) => setApplies(applies.map((x, j) => (j === i ? { ...x, dim: e.target.value } : x)))}>
                    {catalog.dimensions.map((d) => <option key={d} value={d}>{d.replaceAll("_", " ")}</option>)}
                  </select>
                  <input aria-label="Values" className={INPUT} value={a.values} placeholder="Sales|Marketing" onChange={(e) => setApplies(applies.map((x, j) => (j === i ? { ...x, values: e.target.value } : x)))} />
                  <button type="button" className="text-xs text-ink-500" onClick={() => setApplies(applies.filter((_, j) => j !== i))}>Remove</button>
                </div>
              ))}
              <p className="text-[11px] text-ink-500">Read from the register row, then the employee master. An employee with no value recorded is not skipped — they follow the missing-input setting below.</p>
            </div>
            <label className="block max-w-md text-xs font-semibold text-ink-700">When an input is missing
              <select className={`mt-1 ${INPUT}`} value={onMissing} onChange={(e) => setOnMissing(e.target.value as OnMissing)}>
                {(Object.keys(ON_MISSING_LABEL) as OnMissing[]).map((k) => <option key={k} value={k}>{ON_MISSING_LABEL[k]}</option>)}
              </select>
            </label>
          </div>
        )}

        <label className="flex items-center gap-2 text-xs font-semibold text-ink-700"><input type="checkbox" checked={blocks} onChange={(e) => setBlocks(e.target.checked)} /> Block sign-off when this check fails</label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs font-semibold text-ink-700">Source notification or policy reference{category === "statutory" ? " *" : ""}<input required={category === "statutory"} className={`mt-1 ${INPUT}`} value={source} onChange={(e) => setSource(e.target.value)} placeholder="Official URL or policy identifier" /></label>
          <label className="text-xs font-semibold text-ink-700">Suggested resolution<input className={`mt-1 ${INPUT}`} value={fix} onChange={(e) => setFix(e.target.value)} placeholder="What HR should review" /></label>
        </div>
        <label className="block text-xs font-semibold text-ink-700">Why this version is needed *<textarea required minLength={8} className={`mt-1 ${INPUT}`} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
        <button type="submit" disabled={create.isPending} className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">Save draft</button>
      </form>
    </CardContent></Card>
  );
}

// ─── Versions ────────────────────────────────────────────────────────────────

type PendingAction = { id: string; verb: "clone" | "rollback" | "retire" | "return" };

function RuleVersions({ rules, canDraft, canPublishStatutory, disabledRules, otherCompanies, onChanged }: {
  rules: Rule[]; canDraft: boolean; canPublishStatutory: boolean; disabledRules: Set<string>;
  otherCompanies: { id: string; name: string }[]; onChanged: () => void;
}) {
  const [period, setPeriod] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [impact, setImpact] = useState<{ id: string; data: Impact } | null>(null);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState("");
  const [diff, setDiff] = useState<Awaited<ReturnType<typeof matrixApi.compare>> | null>(null);
  const [busy, setBusy] = useState(false);

  const byKey = useMemo(() => {
    const m = new Map<string, Rule[]>();
    for (const r of rules) m.set(r.rule_key, [...(m.get(r.rule_key) ?? []), r]);
    return Array.from(m.entries());
  }, [rules]);

  const run = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try {
      await fn();
      toast.success(done);
      setPending(null); setReason(""); setUntil("");
      onChanged();
    } catch (e) {
      toast.error("Refused", { description: e instanceof Error ? e.message : "" });
    } finally {
      setBusy(false);
    }
  };

  const doImpact = async (id: string) => {
    if (!period) { toast.error("Choose a month to test against first"); return; }
    setBusy(true);
    try {
      setImpact({ id, data: await matrixApi.impact(id, `${period}-01`) });
    } catch (e) {
      toast.error("Could not preview", { description: e instanceof Error ? e.message : "" });
    } finally {
      setBusy(false);
    }
  };

  const confirm = () => {
    if (!pending) return;
    const { id, verb } = pending;
    if (verb === "clone") void run(() => matrixApi.clone(id, reason), "Draft created from this version");
    if (verb === "rollback") void run(() => matrixApi.rollback(id, reason), "Rollback drafted — submit and publish it to take effect");
    if (verb === "retire") void run(() => matrixApi.retire(id, until, reason), "Version retired");
    if (verb === "return") void run(() => matrixApi.returnToDraft(id, reason), "Returned to draft");
  };

  return (
    <Card><CardContent className="space-y-4 py-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-ink-900 dark:text-white">Company rules and their versions</h2>
          <p className="text-xs text-ink-500">A version is never edited. Change a rule by drafting its next version; bring an old one back by rolling back to it; stop one by retiring it from a date — months before that keep it.</p>
        </div>
        <label className="text-xs font-semibold text-ink-700">Test against month<input type="month" className={`mt-1 ${INPUT}`} value={period} onChange={(e) => setPeriod(e.target.value)} /></label>
      </div>
      {byKey.length === 0 ? <p className="text-sm text-ink-500">No company rules yet. Built-in validation still runs.</p> : null}

      {selected.length ? (
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-ink-50 p-2 text-xs dark:bg-white/[0.04]">
          <strong>{selected.length} selected</strong>
          <button type="button" disabled={selected.length !== 2 || busy} className="inline-flex items-center gap-1 rounded-lg border border-ink-200 px-2 py-1 font-semibold disabled:opacity-40"
            onClick={async () => { try { setDiff(await matrixApi.compare(selected[0], selected[1])); } catch (e) { toast.error(e instanceof Error ? e.message : "Compare failed"); } }}>
            <GitCompare size={12} /> Compare two
          </button>
          <button type="button" className="text-ink-500" onClick={() => { setSelected([]); setDiff(null); }}>Clear</button>
        </div>
      ) : null}
      {diff ? (
        <div className="rounded-lg border border-ink-200 p-3 text-xs dark:border-white/10">
          <p className="mb-2 font-semibold">{diff.a.rule_key} v{diff.a.version} → {diff.b.rule_key} v{diff.b.version}: {diff.changes.length} difference(s)</p>
          <table className="w-full"><tbody>
            {diff.changes.map((c) => (
              <tr key={c.field} className="border-t border-ink-100 align-top dark:border-white/5">
                <td className="py-1 pr-3 font-semibold">{c.field.replaceAll("_", " ")}</td>
                <td className="py-1 pr-3 text-danger-700">{render(c.field, c.a)}</td>
                <td className="py-1 text-success-700">{render(c.field, c.b)}</td>
              </tr>
            ))}
          </tbody></table>
        </div>
      ) : null}

      <div className="divide-y divide-ink-200 dark:divide-white/10">
        {byKey.map(([key, versions]) => (
          <div key={key} className="py-3">
            <p className="mb-2 flex items-center gap-2 text-sm font-semibold text-ink-900 dark:text-white">
              <History size={14} className="text-ink-400" /> {key}
              {disabledRules.has(key) ? <span className="rounded bg-ink-200 px-1 text-[10px] uppercase text-ink-600">disabled</span> : null}
            </p>
            <div className="space-y-2">
              {versions.map((r) => {
                const latest = r.version === versions[0].version;
                return (
                  <div key={r.id} className="rounded-lg border border-ink-200/70 p-3 dark:border-white/10">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <label className="flex min-w-0 flex-1 gap-2">
                        <input type="checkbox" aria-label={`Select ${r.rule_key} v${r.version}`} checked={selected.includes(r.id)}
                          onChange={(e) => setSelected(e.target.checked ? [...selected, r.id] : selected.filter((x) => x !== r.id))} />
                        <span className="min-w-0">
                          <span className="block text-sm text-ink-900 dark:text-white">
                            v{r.version} · {r.name}{" "}
                            <span className={cn("ml-1 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase", STATUS_TONE[r.status])}>{r.status}</span>
                            {r.editor_mode === "advanced" ? <span className="ml-1 text-[10px] uppercase text-ink-400">advanced</span> : null}
                          </span>
                          <span className="block text-xs text-ink-500">
                            {r.effective_from}{r.effective_to ? ` → ${r.effective_to}` : " onwards"} · {r.severity}{r.blocks_signoff ? " · blocks sign-off" : ""}
                            {r.state ? ` · ${r.state}` : ""}
                            {r.applies_to ? ` · only ${Object.entries(r.applies_to).map(([d, v]) => `${d.replaceAll("_", " ")} ${v.join("/")}`).join(", ")}` : ""}
                          </span>
                          <span className="block text-xs text-ink-600 dark:text-ink-300">
                            {r.condition ? `When ${describeCondition(r.condition)}, expect` : "Expect"} {describeComparison(r.assertion)}.
                            {r.on_missing !== "cannot_validate" ? ` Missing input: ${r.on_missing === "skip" ? "skip" : "fail"}.` : ""}
                          </span>
                          <span className="block text-[11px] text-ink-400">{r.change_reason}{r.retire_reason ? ` · retired: ${r.retire_reason}` : ""}</span>
                        </span>
                      </label>
                      {canDraft ? (
                        <div className="flex flex-wrap items-center gap-1.5 text-xs">
                          <button type="button" disabled={busy} onClick={() => void doImpact(r.id)} className="inline-flex items-center gap-1 rounded-lg border border-ink-200 px-2.5 py-1 font-semibold text-ink-700"><FlaskConical size={12} /> Impact</button>
                          {r.status === "draft" ? <button type="button" disabled={busy} onClick={() => void run(() => matrixApi.act(r.id, "submit"), "Submitted for approval")} className="rounded-lg border border-brand-300 px-2.5 py-1 font-semibold text-brand-700">Submit</button> : null}
                          {r.status === "pending" && (r.category === "custom" || canPublishStatutory) ? <button type="button" disabled={busy} onClick={() => void run(() => matrixApi.act(r.id, "publish"), "Published")} className="inline-flex items-center gap-1 rounded-lg bg-brand-600 px-2.5 py-1 font-semibold text-white"><ShieldCheck size={12} /> Publish</button> : null}
                          {r.status === "pending" ? <button type="button" onClick={() => setPending({ id: r.id, verb: "return" })} className="rounded-lg border border-ink-200 px-2.5 py-1 font-semibold text-ink-700">Return</button> : null}
                          <button type="button" onClick={() => setPending({ id: r.id, verb: "clone" })} className="rounded-lg border border-ink-200 px-2.5 py-1 font-semibold text-ink-700">Clone</button>
                          {!latest ? <button type="button" onClick={() => setPending({ id: r.id, verb: "rollback" })} className="rounded-lg border border-ink-200 px-2.5 py-1 font-semibold text-ink-700">Roll back to this</button> : null}
                          {r.status === "published" ? <button type="button" onClick={() => setPending({ id: r.id, verb: "retire" })} className="rounded-lg border border-ink-200 px-2.5 py-1 font-semibold text-ink-700">Retire</button> : null}
                        </div>
                      ) : null}
                    </div>
                    {pending?.id === r.id ? (
                      <div className="mt-2 flex flex-wrap items-end gap-2 rounded-lg bg-ink-50 p-2 dark:bg-white/[0.04]">
                        <label className="min-w-64 flex-1 text-xs font-semibold text-ink-700">
                          {pending.verb === "clone" ? "Why draft a new version?" : pending.verb === "rollback" ? "Why restore this version?" : pending.verb === "retire" ? "Why retire it?" : "What needs changing?"} (kept in the record)
                          <input className={`mt-1 ${INPUT}`} value={reason} onChange={(e) => setReason(e.target.value)} />
                        </label>
                        {pending.verb === "retire" ? (
                          <label className="text-xs font-semibold text-ink-700">Last day it applies<input type="date" className={`mt-1 ${INPUT}`} value={until} onChange={(e) => setUntil(e.target.value)} /></label>
                        ) : null}
                        <button type="button" disabled={busy || reason.trim().length < 8 || (pending.verb === "retire" && !until)} onClick={confirm} className="rounded-lg bg-brand-600 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">Confirm</button>
                        <button type="button" onClick={() => setPending(null)} className="px-2 py-2 text-xs text-ink-600">Cancel</button>
                      </div>
                    ) : null}
                    {impact?.id === r.id ? <ImpactView data={impact.data} /> : null}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {canDraft && otherCompanies.length && selected.length ? (
        <CopyPanel ruleIds={selected} companies={otherCompanies} />
      ) : null}
    </CardContent></Card>
  );
}

function render(field: string, v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (field === "assertion" && typeof v === "object") return describeComparison(v as Comparison);
  if (field === "condition" && typeof v === "object") return describeCondition(v as Comparison | Group);
  return typeof v === "object" ? JSON.stringify(v) : String(v);
}

function ImpactView({ data }: { data: Impact }) {
  return (
    <div className="mt-2 rounded-lg bg-brand-50 p-3 text-xs text-ink-700 dark:bg-brand-500/10 dark:text-ink-200">
      <p className="font-semibold">
        {data.employees_evaluated} employees in {data.period_month.slice(0, 7)}: {data.outcomes.passed} pass,{" "}
        {data.outcomes.failed} fail, {data.outcomes.cannot_validate} could not be checked,{" "}
        {data.outcomes.skipped} skipped for a missing input, {data.outcomes.out_of_scope} out of scope.
      </p>
      {data.outcomes.skipped && data.outcomes.skipped === data.employees_evaluated - data.outcomes.out_of_scope ? (
        <p className="font-semibold text-warning-800">Every employee in scope was skipped — this version would check nobody. Review its inputs or its missing-input setting.</p>
      ) : null}
      {data.compared_with ? (
        <p>Against v{data.compared_with.version} in force: {data.newly_flagged} newly flagged, {data.no_longer_flagged} no longer flagged, {data.unchanged} unchanged.</p>
      ) : <p>No version of this rule is in force for that month.</p>}
      <div className="mt-2 max-h-40 space-y-1 overflow-auto">
        {data.sample.slice(0, 20).map((f, i) => <p key={`${f.employee_id}-${i}`} className="flex gap-2"><AlertTriangle size={13} className="shrink-0 text-warning-700" /> {f.employee_id}: {f.reason}</p>)}
        {data.sample.length === 0 ? <p className="flex gap-1"><CheckCircle2 size={13} /> Nobody would be flagged.</p> : null}
      </div>
    </div>
  );
}

function CopyPanel({ ruleIds, companies }: { ruleIds: string[]; companies: { id: string; name: string }[] }) {
  const [targets, setTargets] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [plan, setPlan] = useState<CopyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const go = async (dry: boolean) => {
    setBusy(true);
    try {
      const out = await matrixApi.copy({ rule_ids: ruleIds, target_entity_ids: targets, change_reason: reason, dry_run: dry });
      setPlan(out);
      if (!dry) toast.success("Copied as drafts", { description: "Each company approves them under its own rules." });
    } catch (e) {
      toast.error("Not copied", { description: e instanceof Error ? e.message : "" });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-2 rounded-xl border border-ink-200 p-3 text-xs dark:border-white/10">
      <p className="flex items-center gap-2 text-sm font-semibold text-ink-900 dark:text-white"><Copy size={14} /> Copy the selected versions to other companies</p>
      <p className="text-ink-500">They arrive as drafts, checked against each company&apos;s own components, and go through that company&apos;s approval. Only companies you manage accept them.</p>
      <div className="flex flex-wrap gap-3">
        {companies.map((c) => (
          <label key={c.id} className="flex items-center gap-1.5">
            <input type="checkbox" checked={targets.includes(c.id)} onChange={(e) => { setPlan(null); setTargets(e.target.checked ? [...targets, c.id] : targets.filter((t) => t !== c.id)); }} /> {c.name}
          </label>
        ))}
      </div>
      <input aria-label="Reason for copying" className={INPUT} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why (kept in both companies' audit trails)" />
      <div className="flex gap-2">
        <button type="button" disabled={busy || !targets.length || reason.trim().length < 8} onClick={() => void go(true)} className="rounded-lg border border-ink-200 px-3 py-1.5 font-semibold">Preview</button>
        <button type="button" disabled={busy || !plan?.dry_run} onClick={() => void go(false)} className="rounded-lg bg-brand-600 px-3 py-1.5 font-semibold text-white disabled:opacity-50">Copy</button>
      </div>
      {plan ? (
        <ul className="space-y-1">
          {plan.targets.map((t) => (
            <li key={t.entity_id}>
              <strong>{t.entity_name ?? "Not available"}</strong>{t.status === "not_available" ? " — you do not manage this company" : ": "}
              {t.rules.map((r) => `${r.rule_key} ${r.status.replace("_", " ")}${r.reason ? ` (${r.reason})` : ""}`).join("; ")}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

// ─── Import and export ──────────────────────────────────────────────────────

function ImportCard({ onChanged }: { onChanged: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const download = async () => {
    try {
      const blob = await apiBlob("/api/validation-matrix/export.csv");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = "validation-rules.csv"; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      toast.error("Export failed", { description: e instanceof Error ? e.message : "" });
    }
  };
  const send = async (dry: boolean) => {
    if (!file) return;
    setBusy(true);
    try {
      const out = await matrixApi.importFile(file, dry);
      setPreview(out);
      if (!dry) { toast.success(`${out.created?.length ?? 0} draft(s) created`); onChanged(); setFile(null); }
    } catch (e) {
      toast.error("Not imported", { description: e instanceof Error ? e.message : "" });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card><CardContent className="space-y-3 py-5">
      <h2 className="flex items-center gap-2 text-base font-semibold text-ink-900 dark:text-white"><Upload size={16} /> Import rules from CSV or Excel</h2>
      <p className="text-xs text-ink-500">Export to get the format. Every row is checked exactly as a drafted rule; nothing is created until you have seen the preview, and everything created is a draft that still needs approval.</p>
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={() => void download()} className="inline-flex items-center gap-1 rounded-lg border border-ink-200 px-3 py-1.5 text-xs font-semibold"><Download size={12} /> Export rules (CSV)</button>
        <input type="file" accept=".csv,.xlsx" aria-label="Rules file" className="text-xs" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setPreview(null); }} />
        <button type="button" disabled={!file || busy} onClick={() => void send(true)} className="rounded-lg border border-ink-200 px-3 py-1.5 text-xs font-semibold disabled:opacity-40">Preview</button>
        <button type="button" disabled={!file || busy || !preview?.preview || !!preview.summary.error || !(preview.summary.new + preview.summary.new_version)}
          onClick={() => void send(false)} className="rounded-lg bg-brand-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40">
          Create {preview?.preview ? preview.summary.new + preview.summary.new_version : ""} draft(s)
        </button>
      </div>
      {preview?.rows ? (
        <div className="overflow-x-auto">
          <p className="mb-1 text-xs">{preview.summary.new} new · {preview.summary.new_version} new version · {preview.summary.unchanged} unchanged · <span className={preview.summary.error ? "font-semibold text-danger-700" : ""}>{preview.summary.error} with errors</span></p>
          <table className="w-full text-xs"><thead><tr className="text-left text-ink-500"><th className="py-1 pr-2">Row</th><th className="pr-2">Rule</th><th className="pr-2">Result</th><th>Detail</th></tr></thead><tbody>
            {preview.rows.map((r) => (
              <tr key={r.row} className="border-t border-ink-100 align-top dark:border-white/5">
                <td className="py-1 pr-2">{r.row}</td>
                <td className="pr-2 font-mono">{r.rule_key}</td>
                <td className={cn("pr-2 font-semibold", r.status === "error" ? "text-danger-700" : "text-ink-700")}>{r.status.replace("_", " ")}</td>
                <td>{r.errors.length ? r.errors.join("; ") : r.changes?.length ? `changes ${r.changes.join(", ")} (was v${r.current_version})` : ""}</td>
              </tr>
            ))}
          </tbody></table>
        </div>
      ) : null}
    </CardContent></Card>
  );
}
