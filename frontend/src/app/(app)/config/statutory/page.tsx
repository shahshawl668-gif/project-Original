"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Dialog } from "@/components/ui/drawer";
import { SaveBar } from "@/components/ui/save-bar";
import { Tabs } from "@/components/ui/tabs";
import { useEntity } from "@/context/EntityContext";
import { dateTime, plural } from "@/lib/format";
import { diffObjects, useUnsavedChanges } from "@/lib/unsaved";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { periodLabel } from "@/lib/workspace";
import { DatedChanges } from "@/components/config/DatedChanges";
import {
  Shield, Settings2, RefreshCw,
  ChevronDown, ChevronUp, Beaker, Plus, Trash2,
  ToggleLeft, ToggleRight,
} from "lucide-react";
import {
  type PFConfig, type ESICConfig, type ComponentMappingConfig,
  type TenantStatutoryConfig, type StatutoryConfigResponse,
  defaultPFConfig, defaultESICConfig,
  getStatutoryConfig, saveStatutoryConfig, resetStatutoryConfig, testExpression, statutoryVersionsApi,
} from "@/lib/statutory-config";

// ─── small helpers ────────────────────────────────────────────────────────────

const pct = (v: string) => `${(parseFloat(v) * 100).toFixed(4).replace(/\.?0+$/, "")}%`;

function Section({ title, icon, children, defaultOpen = true }: {
  title: string; icon?: React.ReactNode; children: React.ReactNode; defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="overflow-hidden rounded-xl border border-ink-200 bg-white shadow-soft">
      <button
        type="button"
        aria-expanded={open}
        className="flex w-full items-center justify-between px-5 py-3.5 text-left transition-colors hover:bg-ink-50"
        onClick={() => setOpen((o) => !o)}
      >
        <div className="flex items-center gap-2">
          {icon}
          <span className="text-[15px] font-semibold text-ink-900">
            {title}
          </span>
        </div>
        {open ? (
          <ChevronUp size={16} className="text-ink-500" />
        ) : (
          <ChevronDown size={16} className="text-ink-500" />
        )}
      </button>
      {open && (
        <div className="border-t border-ink-100 px-5 pb-5 pt-4">
          {children}
        </div>
      )}
    </section>
  );
}

function Field({ label, help, children }: { label: string; help?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[13px] font-medium text-ink-800">{label}</span>
      {children}
      {help && <span className="text-xs text-ink-500">{help}</span>}
    </label>
  );
}

function NumberInput({ value, onChange, step = "0.0001", min = "0", max = "1" }: {
  value: string; onChange: (v: string) => void;
  step?: string; min?: string; max?: string;
}) {
  return (
    <input
      type="number"
      value={value}
      step={step}
      min={min}
      max={max}
      className="num h-9 w-full rounded-lg border border-ink-200 bg-white px-3 text-[13px] text-ink-900 shadow-soft transition-colors hover:border-ink-300 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

function TextInput({ value, onChange, placeholder = "" }: {
  value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  return (
    <input
      type="text"
      value={value}
      placeholder={placeholder}
      className="h-9 w-full rounded-lg border border-ink-200 bg-white px-3 font-mono text-[13px] text-ink-900 shadow-soft transition-colors placeholder:text-ink-400 hover:border-ink-300 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`inline-flex items-center gap-2 text-[13px] font-medium transition-colors ${
        checked ? "text-ink-900" : "text-ink-600"
      }`}
    >
      {checked ? (
        <ToggleRight size={20} className="text-brand-600" />
      ) : (
        <ToggleLeft size={20} className="text-ink-500" />
      )}
      {label}
    </button>
  );
}

function TagInput({ values, onChange, placeholder }: {
  values: string[]; onChange: (v: string[]) => void; placeholder?: string;
}) {
  const [input, setInput] = useState("");
  const add = () => {
    const v = input.trim();
    if (v && !values.includes(v)) {
      onChange([...values, v]);
      setInput("");
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {values.map((v) => (
        <span
          key={v}
          className="inline-flex items-center gap-1 rounded-full bg-brand-100 px-2 py-0.5 text-xs font-semibold text-brand-700"
        >
          {v}
          <button onClick={() => onChange(values.filter((x) => x !== v))}>
            <Trash2 size={10} />
          </button>
        </span>
      ))}
      <input
        className="min-w-24 rounded border border-dashed border-ink-300 px-2 py-0.5 text-sm transition-colors focus:border-brand-400 focus:outline-none"
        placeholder={placeholder || "Add…"}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            add();
          }
        }}
      />
      <button onClick={add} className="text-brand-600 hover:text-brand-800">
        <Plus size={14} />
      </button>
    </div>
  );
}

// ─── Expression tester ────────────────────────────────────────────────────────

function ExprTester({ expression, sampleCtx }: { expression: string; sampleCtx: Record<string, unknown> }) {
  const [result, setResult] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const run = async () => {
    setRunning(true);
    try {
      const r = await testExpression(expression, sampleCtx);
      setResult(r.eval_ok ? `✓ ${r.result} (${r.result_type})` : `✗ ${r.error}`);
    } catch {
      setResult("Network error");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="mt-2 flex items-center gap-3">
      <button
        onClick={run}
        disabled={running}
        className="inline-flex items-center gap-1.5 rounded-lg bg-brand-50 px-3 py-1.5 text-xs font-semibold text-brand-700 transition-colors hover:bg-brand-100 disabled:opacity-50"
      >
        <Beaker size={12} /> {running ? "Testing…" : "Test expression"}
      </button>
      {result && (
        <span
          className={`font-mono text-xs ${
            result.startsWith("✓")
              ? "text-success-700"
              : "text-danger-600"
          }`}
        >
          {result}
        </span>
      )}
    </div>
  );
}

// ─── PF Config section ────────────────────────────────────────────────────────

function PFConfigPanel({ cfg, onChange, advanced }: { cfg: PFConfig; onChange: (c: PFConfig) => void; advanced: boolean }) {
  const set = <K extends keyof PFConfig>(key: K, val: PFConfig[K]) => onChange({ ...cfg, [key]: val });
  const setRates = (k: keyof PFConfig["rates"], v: string) => set("rates", { ...cfg.rates, [k]: v });
  const setWage  = (k: keyof PFConfig["wage"],  v: unknown) => set("wage",  { ...cfg.wage,  [k]: v });
  const setElig  = (k: keyof PFConfig["eligibility"], v: unknown) => set("eligibility", { ...cfg.eligibility, [k]: v });
  const setVol   = (k: keyof PFConfig["voluntary"], v: unknown) => set("voluntary", { ...cfg.voluntary, [k]: v });

  return (
    <div className="space-y-5">
      {/* Rates */}
      <div>
        <p className="mb-3 text-xs font-semibold text-ink-500">
          Contribution rates
        </p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {(["employee_rate", "employer_rate", "eps_rate", "edli_rate", "admin_rate"] as const).map(
            (k) => (
              <Field key={k} label={({ employee_rate: "Employee", employer_rate: "Employer", eps_rate: "EPS", edli_rate: "EDLI", admin_rate: "Admin charges" } as const)[k]} help={pct(cfg.rates[k])}>
                <NumberInput value={cfg.rates[k]} onChange={(v) => setRates(k, v)} />
              </Field>
            ),
          )}
        </div>
      </div>

      {/* Wage */}
      <div>
        <p className="mb-3 text-xs font-semibold text-ink-500">
          PF wage computation
        </p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Wage ceiling (₹)" help="Statutory ceiling — ₹15,000">
            <NumberInput value={cfg.wage.wage_ceiling} onChange={v => setWage("wage_ceiling", v)} step="500" min="0" max="999999"/>
          </Field>
          <div className="flex flex-col gap-3 pt-1">
            <Toggle
              checked={cfg.wage.restrict_to_ceiling}
              onChange={v => setWage("restrict_to_ceiling", v)}
              label="Restrict PF wage to ceiling"
            />
            <Toggle
              checked={cfg.wage.use_pf_applicable_flag}
              onChange={v => setWage("use_pf_applicable_flag", v)}
              label="Use component pf_applicable flag"
            />
          </div>
        </div>
        {advanced && !cfg.wage.use_pf_applicable_flag && (
          <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="Include components" help="Only these components contribute to PF wage">
              <TagInput values={cfg.wage.include_components} onChange={v => setWage("include_components", v)} placeholder="basic"/>
            </Field>
            <Field label="Exclude components" help="These are excluded even if pf_applicable=True">
              <TagInput values={cfg.wage.exclude_components} onChange={v => setWage("exclude_components", v)} placeholder="bonus"/>
            </Field>
          </div>
        )}
        {advanced && cfg.wage.use_pf_applicable_flag && cfg.wage.exclude_components.length > 0 && (
          <div className="mt-3">
            <Field label="Force-exclude from PF wage" help="Even if marked pf_applicable=True">
              <TagInput values={cfg.wage.exclude_components} onChange={v => setWage("exclude_components", v)} placeholder="component name"/>
            </Field>
          </div>
        )}
      </div>

      {/* Above-ceiling mode */}
      {advanced ? <>
      <div>
        <p className="mb-2 text-xs font-semibold text-ink-500">
          Above-ceiling contributions
        </p>
        <select
          value={cfg.above_ceiling_mode}
          onChange={(e) => set("above_ceiling_mode", e.target.value as PFConfig["above_ceiling_mode"])}
          className="num h-9 w-full rounded-lg border border-ink-200 bg-white px-3 text-[13px] text-ink-900 shadow-soft transition-colors hover:border-ink-300 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
        >
          <option value="none">None — always cap at ceiling</option>
          <option value="employee_choice">Employee choice — voluntary above ceiling</option>
          <option value="employer_choice">Employer choice — employer contributes on full wage</option>
        </select>
      </div>

      {/* Voluntary PF */}
      <div>
        <p className="mb-3 text-xs font-semibold text-ink-500">
          Voluntary PF
        </p>
        <Toggle
          checked={cfg.voluntary.enabled}
          onChange={(v) => setVol("enabled", v)}
          label="Enable voluntary PF components"
        />
        {cfg.voluntary.enabled && (
          <div className="mt-3">
            <Field label="VPF component names" help="Columns that carry voluntary PF amounts in the register">
              <TagInput values={cfg.voluntary.components} onChange={v => setVol("components", v)} placeholder="vpf"/>
            </Field>
          </div>
        )}
      </div>

      {/* Eligibility */}
      <div>
        <p className="mb-3 text-xs font-semibold text-ink-500">
          PF eligibility
        </p>
        <div className="space-y-3">
          <Field label="Eligibility expression" help="Python-safe expression. Vars: pf_wage, gross, employee_type">
            <TextInput value={cfg.eligibility.expression} onChange={v => setElig("expression", v)} placeholder="pf_wage > 0"/>
            <ExprTester expression={cfg.eligibility.expression} sampleCtx={{ pf_wage: 15000, gross: 35000, employee_type: "employee" }}/>
          </Field>
          <Field label="Exempt employment types" help="These types are never PF-eligible (e.g. contractor, intern)">
            <TagInput values={cfg.eligibility.exempt_employment_types} onChange={v => setElig("exempt_employment_types", v)} placeholder="contractor"/>
          </Field>
        </div>
      </div>
      </> : null}
    </div>
  );
}

// ─── ESIC Config section ──────────────────────────────────────────────────────

function ESICConfigPanel({ cfg, onChange, advanced }: { cfg: ESICConfig; onChange: (c: ESICConfig) => void; advanced: boolean }) {
  const set = <K extends keyof ESICConfig>(key: K, val: ESICConfig[K]) => onChange({ ...cfg, [key]: val });
  const setRates   = (k: keyof ESICConfig["rates"],   v: string)  => set("rates",   { ...cfg.rates,   [k]: v });
  const setWage    = (k: keyof ESICConfig["wage"],    v: unknown) => set("wage",    { ...cfg.wage,    [k]: v });
  const setRound   = (k: keyof ESICConfig["rounding"],v: unknown) => set("rounding",{ ...cfg.rounding,[k]: v });
  const setElig    = (k: keyof ESICConfig["eligibility"], v: unknown) => set("eligibility", { ...cfg.eligibility, [k]: v });

  return (
    <div className="space-y-5">
      {/* Rates */}
      <div>
        <p className="mb-3 text-xs font-semibold text-ink-500">
          Contribution rates
        </p>
        <div className="grid max-w-xs grid-cols-2 gap-3">
          <Field label="Employee" help={pct(cfg.rates.employee_rate)}>
            <NumberInput value={cfg.rates.employee_rate} onChange={(v) => setRates("employee_rate", v)} />
          </Field>
          <Field label="Employer" help={pct(cfg.rates.employer_rate)}>
            <NumberInput value={cfg.rates.employer_rate} onChange={(v) => setRates("employer_rate", v)} />
          </Field>
        </div>
      </div>

      {/* Wage */}
      <div>
        <p className="mb-3 text-xs font-semibold text-ink-500">
          ESIC wage computation
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="Wage ceiling (₹)" help="Employees above this are ESIC-exempt">
            <NumberInput value={cfg.wage.wage_ceiling} onChange={v => setWage("wage_ceiling", v)} step="500" min="0" max="999999"/>
          </Field>
          <div className="pt-1">
            <Toggle
              checked={cfg.wage.use_esic_applicable_flag}
              onChange={v => setWage("use_esic_applicable_flag", v)}
              label="Use component esic_applicable flag"
            />
          </div>
        </div>
        {advanced && !cfg.wage.use_esic_applicable_flag && (
          <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="Include components">
              <TagInput values={cfg.wage.include_components} onChange={v => setWage("include_components", v)} placeholder="basic"/>
            </Field>
            <Field label="Exclude components">
              <TagInput values={cfg.wage.exclude_components} onChange={v => setWage("exclude_components", v)} placeholder="bonus"/>
            </Field>
          </div>
        )}
      </div>

      {/* Rounding */}
      <div>
        <p className="mb-3 text-xs font-semibold text-ink-500">
          Rounding
        </p>
        <div className="flex items-center gap-4">
          {(["up", "down", "nearest"] as const).map((m) => (
            <label
              key={m}
              className="flex cursor-pointer items-center gap-2 text-sm text-ink-700"
            >
              <input
                type="radio"
                name="esic_round"
                value={m}
                checked={cfg.rounding.mode === m}
                onChange={() => setRound("mode", m)}
                className="accent-brand-600"
              />
              {m.charAt(0).toUpperCase() + m.slice(1)}
            </label>
          ))}
        </div>
        {advanced ? <div className="mt-3">
          <Field label="Custom expression (optional)" help="Vars: esic_wage, rate_emp, rate_er, ceil, floor, round. Leave blank to use rate × wage.">
            <TextInput value={cfg.rounding.expression} onChange={v => setRound("expression", v)} placeholder="ceil(esic_wage * 0.0075)"/>
            {cfg.rounding.expression && (
              <ExprTester expression={cfg.rounding.expression} sampleCtx={{ esic_wage: 18000, rate_emp: 0.0075, rate_er: 0.0325 }}/>
            )}
          </Field>
        </div> : null}
      </div>

      {/* Eligibility */}
      {advanced ? <div>
        <p className="mb-3 text-xs font-semibold text-ink-500">
          Eligibility & entry/exit
        </p>
        <div className="space-y-3">
          <Field label="Eligibility expression" help="Vars: esic_wage, esic_ceiling, employee_type">
            <TextInput value={cfg.eligibility.expression} onChange={v => setElig("expression", v)}/>
            <ExprTester expression={cfg.eligibility.expression} sampleCtx={{ esic_wage: 18000, esic_ceiling: 21000, employee_type: "employee" }}/>
          </Field>
          <Field label="Exempt employment types">
            <TagInput values={cfg.eligibility.exempt_employment_types} onChange={v => setElig("exempt_employment_types", v)} placeholder="contractor"/>
          </Field>
          <div className="flex flex-col gap-2">
            <Toggle checked={cfg.eligibility.full_month_on_entry} onChange={v => setElig("full_month_on_entry", v)} label="Full-month ESIC on joining month"/>
            <Toggle checked={cfg.eligibility.continue_month_on_exit} onChange={v => setElig("continue_month_on_exit", v)} label="Continue ESIC in exit month"/>
          </div>
        </div>
      </div> : null}
    </div>
  );
}

// ─── Component mapping panel ──────────────────────────────────────────────────

function ComponentMappingPanel({ cfg, onChange }: {
  cfg: ComponentMappingConfig; onChange: (c: ComponentMappingConfig) => void;
}) {
  const addEntry = () => onChange({
    ...cfg,
    entries: [...cfg.entries, { upload_column: "", component_name: "", pf_applicable: false, esic_applicable: false, included_in_wages: true, taxable: true }],
  });
  const removeEntry = (i: number) => onChange({ ...cfg, entries: cfg.entries.filter((_, idx) => idx !== i) });
  const updateEntry = (i: number, key: string, val: unknown) =>
    onChange({ ...cfg, entries: cfg.entries.map((e, idx) => idx === i ? { ...e, [key]: val } : e) });

  return (
    <div className="space-y-4">
      <p className="text-sm text-ink-500">
        Define aliases for upload columns and override component flags without changing ComponentConfig.
      </p>

      <div className="overflow-x-auto rounded-xl border border-ink-200/70">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-ink-50/80 text-[11px] text-ink-500">
              {["Upload column", "Component name", "PF", "ESIC", "In wages", "Taxable", ""].map((h) => (
                <th key={h} className="px-3 py-2 text-left font-semibold">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-100">
            {cfg.entries.map((e, i) => (
              <tr key={i} className="hover:bg-ink-50/40">
                <td className="px-3 py-2">
                  <input
                    type="text"
                    value={e.upload_column}
                    placeholder="column_name"
                    className="w-28 rounded border border-ink-200 bg-white px-2 py-1 text-xs text-ink-900"
                    onChange={(ev) => updateEntry(i, "upload_column", ev.target.value)}
                  />
                </td>
                <td className="px-3 py-2">
                  <input
                    type="text"
                    value={e.component_name}
                    placeholder="Component"
                    className="w-28 rounded border border-ink-200 bg-white px-2 py-1 text-xs text-ink-900"
                    onChange={(ev) => updateEntry(i, "component_name", ev.target.value)}
                  />
                </td>
                {(["pf_applicable", "esic_applicable", "included_in_wages", "taxable"] as const).map(
                  (k) => (
                    <td key={k} className="px-3 py-2 text-center">
                      <input
                        type="checkbox"
                        checked={e[k]}
                        className="accent-brand-600"
                        onChange={(ev) => updateEntry(i, k, ev.target.checked)}
                      />
                    </td>
                  ),
                )}
                <td className="px-3 py-2">
                  <button
                    onClick={() => removeEntry(i)}
                    className="text-danger-400 transition-colors hover:text-danger-600"
                  >
                    <Trash2 size={12} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <button
        onClick={addEntry}
        className="inline-flex items-center gap-1.5 rounded-xl border border-brand-200 px-3 py-1.5 text-xs font-semibold text-brand-600 transition-colors hover:bg-brand-50"
      >
        <Plus size={12} /> Add alias
      </button>

      <div className="mt-4">
        <Field label="Ignore columns" help="These columns are silently skipped during parsing (no COMP-001 warning)">
          <TagInput values={cfg.ignore_columns} onChange={v => onChange({ ...cfg, ignore_columns: v })} placeholder="notes"/>
        </Field>
      </div>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

const EMPTY_CFG: TenantStatutoryConfig = {
  pf: defaultPFConfig,
  esic: defaultESICConfig,
  component_mapping: { entries: [], ignore_columns: [] },
};

export default function StatutoryConfigPage() {
  const { activeRole, entity } = useEntity();
  const qc = useQueryClient();
  const canWrite = activeRole !== "viewer";
  const [scheduling, setScheduling] = useState(false);
  const [fromMonth, setFromMonth] = useState("");
  const [note, setNote] = useState("");
  const versions = useQuery({ queryKey: ["statutory-versions", entity?.id], queryFn: statutoryVersionsApi.list, enabled: !!entity });
  const inForce = versions.data?.in_force_now;
  const [cfg, setCfg] = useState<TenantStatutoryConfig>(EMPTY_CFG);
  // What the server holds. Unsaved changes are the difference from this.
  const [baseline, setBaseline] = useState<TenantStatutoryConfig>(EMPTY_CFG);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

  useEffect(() => {
    try { setAdvanced(localStorage.getItem("pol_statutory_mode") === "advanced"); } catch { /* default basic */ }
    setLoading(true);
    getStatutoryConfig()
      .then((data) => {
        const loaded = { pf: data.pf, esic: data.esic, component_mapping: data.component_mapping };
        setCfg(loaded);
        setBaseline(loaded);
        setUpdatedAt(data.updated_at);
      })
      // Never edit shipped defaults as though they were this company's saved
      // configuration: say it did not load, and do not offer to save over it.
      .catch(() => setLoadFailed(true))
      .finally(() => setLoading(false));
  }, []);

  const changes = useMemo(() => diffObjects(baseline, cfg), [baseline, cfg]);
  useUnsavedChanges(changes.length > 0);

  const setMode = (m: string) => {
    const adv = m === "advanced";
    setAdvanced(adv);
    try { localStorage.setItem("pol_statutory_mode", adv ? "advanced" : "basic"); } catch { /* per-session only */ }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const data = await saveStatutoryConfig(cfg);
      const saved = { pf: data.pf, esic: data.esic, component_mapping: data.component_mapping };
      setCfg(saved);
      setBaseline(saved);
      setUpdatedAt(data.updated_at);
      toast.success("Statutory configuration saved", { description: "The next validation run uses it; the change is in the audit trail." });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  // Keep the edits as a draft that takes effect from a month; the form goes
  // back to the configuration in force, which the draft does not change.
  const handleSchedule = async () => {
    setSaving(true);
    setError(null);
    try {
      const v = await statutoryVersionsApi.draft({ effective_from: `${fromMonth}-01`, config: cfg, note: note.trim() || null });
      setScheduling(false);
      setCfg(baseline);
      setNote("");
      await qc.invalidateQueries({ queryKey: ["statutory-versions", entity?.id] });
      toast.success(`Drafted as change ${v.number}, from ${periodLabel(`${fromMonth}-01`)}`, { description: "Nothing is in force until a manager publishes it — see Dated changes." });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Not drafted");
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    setConfirmReset(false);
    setSaving(true);
    setError(null);
    try {
      const data = await resetStatutoryConfig();
      const saved = { pf: data.pf, esic: data.esic, component_mapping: data.component_mapping };
      setCfg(saved);
      setBaseline(saved);
      setUpdatedAt(data.updated_at);
      toast.success("Shipped defaults restored");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Reset failed");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="mx-auto max-w-5xl space-y-4">
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-4 w-full max-w-lg" />
        {[1, 2, 3].map((i) => <Skeleton key={i} className="h-52 w-full rounded-xl" />)}
      </div>
    );
  }

  if (loadFailed) {
    return (
      <div className="mx-auto max-w-5xl space-y-5">
        <PageHeader title="Statutory configuration" />
        <AlertBanner variant="error" title="This company's statutory configuration could not be loaded">
          Nothing is shown rather than the shipped defaults, so that nobody edits — or saves — figures that are not this company&apos;s. Reload the page to try again.
        </AlertBanner>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <PageHeader
        title="Statutory configuration"
        description="PF and ESIC rates, wage rules, rounding and eligibility for this company, and how register columns map onto them."
        meta={updatedAt ? <span>Last saved {dateTime(updatedAt)} · <Link href="/audit" className="underline-offset-2 hover:underline">change history in the audit trail</Link></span> : null}
        actions={canWrite ? (
          <Button variant="destructive-outline" type="button" onClick={() => setConfirmReset(true)} disabled={saving}>
            <RefreshCw size={14} strokeWidth={2} /> Reset to shipped defaults
          </Button>
        ) : null}
      />

      <div className="flex flex-wrap items-end justify-between gap-3">
        <Tabs
          label="Editor mode"
          value={advanced ? "advanced" : "basic"}
          onChange={setMode}
          items={[{ id: "basic", label: "Basic" }, { id: "advanced", label: "Advanced" }]}
          className="min-w-[12rem]"
        />
        <p className="max-w-xl text-xs text-ink-500">
          {advanced
            ? "Advanced shows everything: component lists, eligibility expressions with a tester, custom rounding and column overrides."
            : "Basic shows rates, ceilings and the switches most companies change. Everything else keeps its value."}
        </p>
      </div>

      {error ? <AlertBanner variant="error" title="Not saved">{error}</AlertBanner> : null}

      <AlertBanner variant="info" title="How a change takes effect">
        <b>Save changes</b> applies to every month that no dated change covers, from the <b>next validation run</b>. <b>Schedule from a month…</b> keeps them instead as a draft that takes effect from a month you choose, and changes nothing until a manager publishes it (Dated changes, below). Either way, runs already made keep the configuration they were validated with, and a validated month the change covers is marked <i>revalidation required</i>. Every save and publication is in the audit trail. Expressions run in a restricted sandbox — no imports, no attribute access.
      </AlertBanner>

      {inForce?.version ? (
        <AlertBanner variant="warning" title={`This month uses change ${inForce.version}, not the configuration below`}>
          Change {inForce.version} has been in force since {periodLabel(inForce.effective_from!)}. The configuration below applies to months before any dated change; editing it does not alter a month a change covers. See Dated changes at the foot of the page.
        </AlertBanner>
      ) : null}

      {!canWrite ? <AlertBanner variant="info">Your role can read this configuration but not change it.</AlertBanner> : null}

      <fieldset disabled={!canWrite} className="space-y-5">
        <Section title="Provident Fund (PF)" icon={<Shield size={16} className="text-ink-500" />}>
          <PFConfigPanel cfg={cfg.pf} onChange={(pf) => setCfg((c) => ({ ...c, pf }))} advanced={advanced} />
        </Section>

        <Section title="Employee State Insurance (ESIC)" icon={<Shield size={16} className="text-ink-500" />}>
          <ESICConfigPanel cfg={cfg.esic} onChange={(esic) => setCfg((c) => ({ ...c, esic }))} advanced={advanced} />
        </Section>

        {advanced ? (
          <Section title="Component mapping overrides" icon={<Settings2 size={16} className="text-ink-500" />} defaultOpen={false}>
            <ComponentMappingPanel
              cfg={cfg.component_mapping}
              onChange={(component_mapping) => setCfg((c) => ({ ...c, component_mapping }))}
            />
          </Section>
        ) : null}
      </fieldset>

      <DatedChanges />

      <SaveBar
        changes={changes}
        saving={saving}
        onSave={() => void handleSave()}
        onDiscard={() => setCfg(baseline)}
        note="saving applies them to every month without a dated change"
        canSave={canWrite}
        secondary={canWrite ? <Button variant="outline" disabled={saving} onClick={() => setScheduling(true)}>Schedule from a month…</Button> : null}
      />

      <Dialog
        open={scheduling}
        onClose={() => setScheduling(false)}
        title="Schedule these changes from a month"
        description="They are kept as a draft — nothing changes until a manager publishes it. From its month they apply to validation and costing, until the next dated change."
        footer={
          <>
            <Button variant="outline" onClick={() => setScheduling(false)}>Cancel</Button>
            <Button disabled={!fromMonth || saving} onClick={() => void handleSchedule()}>Save as a draft</Button>
          </>
        }
      >
        <div className="space-y-3">
          <label className="block text-xs font-medium text-ink-700">Takes effect from
            <input type="month" className="mt-1 block h-9 rounded-lg border border-ink-200 bg-white px-2.5 text-[13px] text-ink-900" value={fromMonth} onChange={(e) => setFromMonth(e.target.value)} />
          </label>
          <label className="block text-xs font-medium text-ink-700">Why (optional)
            <textarea className="mt-1 block min-h-[56px] w-full rounded-lg border border-ink-200 bg-white px-2.5 py-2 text-[13px] text-ink-900" maxLength={2000} value={note} placeholder="e.g. EPFO notification of 1 April raising the wage ceiling" onChange={(e) => setNote(e.target.value)} />
          </label>
          <p className="text-xs text-ink-500">{plural(changes.length, "field")} will change from that month. The form then returns to the configuration in force.</p>
        </div>
      </Dialog>

      <Dialog
        open={confirmReset}
        onClose={() => setConfirmReset(false)}
        title="Reset to the shipped defaults?"
        description="PF, ESIC and column mapping return to the defaults the product ships with. The shipped defaults are not a certification of current law. The reset is recorded in the audit trail; runs already made are unaffected."
        footer={
          <>
            <Button variant="outline" onClick={() => setConfirmReset(false)}>Cancel</Button>
            <Button variant="destructive" onClick={() => void handleReset()}>Reset configuration</Button>
          </>
        }
      >
        {changes.length ? <p className="text-[13px] text-warning-800">Your {plural(changes.length, "unsaved change")} will be lost as well.</p> : null}
      </Dialog>
    </div>
  );
}
