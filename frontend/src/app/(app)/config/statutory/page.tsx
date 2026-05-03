"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import {
  Shield, Settings2, CheckCircle2, RefreshCw,
  Save, ChevronDown, ChevronUp, Beaker, Plus, Trash2,
  ToggleLeft, ToggleRight,
} from "lucide-react";
import {
  type PFConfig, type ESICConfig, type ComponentMappingConfig,
  type TenantStatutoryConfig, type StatutoryConfigResponse,
  defaultPFConfig, defaultESICConfig,
  getStatutoryConfig, saveStatutoryConfig, resetStatutoryConfig, testExpression,
} from "@/lib/statutory-config";

// ─── small helpers ────────────────────────────────────────────────────────────

const pct = (v: string) => `${(parseFloat(v) * 100).toFixed(4).replace(/\.?0+$/, "")}%`;

function Section({ title, icon, children, defaultOpen = true }: {
  title: string; icon?: React.ReactNode; children: React.ReactNode; defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="overflow-hidden rounded-2xl border border-ink-200/70 bg-white shadow-soft ring-1 ring-ink-900/[0.03] dark:border-white/[0.07] dark:bg-ink-900/70 dark:ring-white/[0.04]">
      <button
        className="flex w-full items-center justify-between px-5 py-4 text-left transition-colors hover:bg-ink-50 dark:hover:bg-white/[0.04]"
        onClick={() => setOpen((o) => !o)}
      >
        <div className="flex items-center gap-2">
          {icon}
          <span className="font-display text-sm font-semibold text-ink-800 dark:text-white">
            {title}
          </span>
        </div>
        {open ? (
          <ChevronUp size={16} className="text-ink-400 dark:text-ink-500" />
        ) : (
          <ChevronDown size={16} className="text-ink-400 dark:text-ink-500" />
        )}
      </button>
      {open && (
        <div className="border-t border-ink-100 px-5 pb-5 pt-4 dark:border-white/[0.06]">
          {children}
        </div>
      )}
    </div>
  );
}

function Field({ label, help, children }: { label: string; help?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-[11px] font-bold uppercase tracking-[0.12em] text-ink-600 dark:text-ink-300">
        {label}
      </label>
      {children}
      {help && <p className="text-xs text-ink-400 dark:text-ink-500">{help}</p>}
    </div>
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
      className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900 shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-brand-500/40 dark:border-white/10 dark:bg-white/[0.04] dark:text-white"
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
      className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900 shadow-sm transition-colors placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-brand-500/40 dark:border-white/10 dark:bg-white/[0.04] dark:text-white dark:placeholder:text-ink-500"
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      className={`inline-flex items-center gap-2 text-sm font-medium transition-colors ${
        checked ? "text-brand-700 dark:text-brand-300" : "text-ink-500 dark:text-ink-400"
      }`}
    >
      {checked ? (
        <ToggleRight size={20} className="text-brand-600 dark:text-brand-300" />
      ) : (
        <ToggleLeft size={20} className="text-ink-400 dark:text-ink-500" />
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
          className="inline-flex items-center gap-1 rounded-full bg-brand-100 px-2 py-0.5 text-xs font-semibold text-brand-700 dark:bg-brand-500/15 dark:text-brand-300"
        >
          {v}
          <button onClick={() => onChange(values.filter((x) => x !== v))}>
            <Trash2 size={10} />
          </button>
        </span>
      ))}
      <input
        className="min-w-24 rounded border border-dashed border-ink-300 px-2 py-0.5 text-sm transition-colors focus:border-brand-400 focus:outline-none dark:border-white/15 dark:bg-transparent dark:text-white dark:focus:border-brand-400"
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
      <button onClick={add} className="text-brand-600 hover:text-brand-800 dark:text-brand-300">
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
        className="inline-flex items-center gap-1.5 rounded-lg bg-brand-50 px-3 py-1.5 text-xs font-semibold text-brand-700 transition-colors hover:bg-brand-100 disabled:opacity-50 dark:bg-brand-500/15 dark:text-brand-300 dark:hover:bg-brand-500/25"
      >
        <Beaker size={12} /> {running ? "Testing…" : "Test expression"}
      </button>
      {result && (
        <span
          className={`font-mono text-xs ${
            result.startsWith("✓")
              ? "text-success-700 dark:text-success-300"
              : "text-danger-600 dark:text-danger-300"
          }`}
        >
          {result}
        </span>
      )}
    </div>
  );
}

// ─── PF Config section ────────────────────────────────────────────────────────

function PFConfigPanel({ cfg, onChange }: { cfg: PFConfig; onChange: (c: PFConfig) => void }) {
  const set = <K extends keyof PFConfig>(key: K, val: PFConfig[K]) => onChange({ ...cfg, [key]: val });
  const setRates = (k: keyof PFConfig["rates"], v: string) => set("rates", { ...cfg.rates, [k]: v });
  const setWage  = (k: keyof PFConfig["wage"],  v: unknown) => set("wage",  { ...cfg.wage,  [k]: v });
  const setElig  = (k: keyof PFConfig["eligibility"], v: unknown) => set("eligibility", { ...cfg.eligibility, [k]: v });
  const setVol   = (k: keyof PFConfig["voluntary"], v: unknown) => set("voluntary", { ...cfg.voluntary, [k]: v });

  return (
    <div className="space-y-5">
      {/* Rates */}
      <div>
        <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.12em] text-ink-500 dark:text-ink-300">
          Contribution rates
        </p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {(["employee_rate", "employer_rate", "eps_rate", "edli_rate", "admin_rate"] as const).map(
            (k) => (
              <Field key={k} label={k.replace("_rate", "").toUpperCase()} help={pct(cfg.rates[k])}>
                <NumberInput value={cfg.rates[k]} onChange={(v) => setRates(k, v)} />
              </Field>
            ),
          )}
        </div>
      </div>

      {/* Wage */}
      <div>
        <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.12em] text-ink-500 dark:text-ink-300">
          PF wage computation
        </p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Wage Ceiling (₹)" help="Statutory ceiling — ₹15,000">
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
        {!cfg.wage.use_pf_applicable_flag && (
          <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="Include components" help="Only these components contribute to PF wage">
              <TagInput values={cfg.wage.include_components} onChange={v => setWage("include_components", v)} placeholder="basic"/>
            </Field>
            <Field label="Exclude components" help="These are excluded even if pf_applicable=True">
              <TagInput values={cfg.wage.exclude_components} onChange={v => setWage("exclude_components", v)} placeholder="bonus"/>
            </Field>
          </div>
        )}
        {cfg.wage.use_pf_applicable_flag && cfg.wage.exclude_components.length > 0 && (
          <div className="mt-3">
            <Field label="Force-exclude from PF wage" help="Even if marked pf_applicable=True">
              <TagInput values={cfg.wage.exclude_components} onChange={v => setWage("exclude_components", v)} placeholder="component name"/>
            </Field>
          </div>
        )}
      </div>

      {/* Above-ceiling mode */}
      <div>
        <p className="mb-2 text-[11px] font-bold uppercase tracking-[0.12em] text-ink-500 dark:text-ink-300">
          Above-ceiling contributions
        </p>
        <select
          value={cfg.above_ceiling_mode}
          onChange={(e) => set("above_ceiling_mode", e.target.value as PFConfig["above_ceiling_mode"])}
          className="w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900 shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-brand-500/40 dark:border-white/10 dark:bg-white/[0.04] dark:text-white"
        >
          <option value="none">None — always cap at ceiling</option>
          <option value="employee_choice">Employee choice — voluntary above ceiling</option>
          <option value="employer_choice">Employer choice — employer contributes on full wage</option>
        </select>
      </div>

      {/* Voluntary PF */}
      <div>
        <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.12em] text-ink-500 dark:text-ink-300">
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
        <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.12em] text-ink-500 dark:text-ink-300">
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
    </div>
  );
}

// ─── ESIC Config section ──────────────────────────────────────────────────────

function ESICConfigPanel({ cfg, onChange }: { cfg: ESICConfig; onChange: (c: ESICConfig) => void }) {
  const set = <K extends keyof ESICConfig>(key: K, val: ESICConfig[K]) => onChange({ ...cfg, [key]: val });
  const setRates   = (k: keyof ESICConfig["rates"],   v: string)  => set("rates",   { ...cfg.rates,   [k]: v });
  const setWage    = (k: keyof ESICConfig["wage"],    v: unknown) => set("wage",    { ...cfg.wage,    [k]: v });
  const setRound   = (k: keyof ESICConfig["rounding"],v: unknown) => set("rounding",{ ...cfg.rounding,[k]: v });
  const setElig    = (k: keyof ESICConfig["eligibility"], v: unknown) => set("eligibility", { ...cfg.eligibility, [k]: v });

  return (
    <div className="space-y-5">
      {/* Rates */}
      <div>
        <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.12em] text-ink-500 dark:text-ink-300">
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
        <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.12em] text-ink-500 dark:text-ink-300">
          ESIC wage computation
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="Wage Ceiling (₹)" help="Employees above this are ESIC-exempt">
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
        {!cfg.wage.use_esic_applicable_flag && (
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
        <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.12em] text-ink-500 dark:text-ink-300">
          Rounding
        </p>
        <div className="flex items-center gap-4">
          {(["up", "down", "nearest"] as const).map((m) => (
            <label
              key={m}
              className="flex cursor-pointer items-center gap-2 text-sm text-ink-700 dark:text-ink-200"
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
        <div className="mt-3">
          <Field label="Custom expression (optional)" help="Vars: esic_wage, rate_emp, rate_er, ceil, floor, round. Leave blank to use rate × wage.">
            <TextInput value={cfg.rounding.expression} onChange={v => setRound("expression", v)} placeholder="ceil(esic_wage * 0.0075)"/>
            {cfg.rounding.expression && (
              <ExprTester expression={cfg.rounding.expression} sampleCtx={{ esic_wage: 18000, rate_emp: 0.0075, rate_er: 0.0325 }}/>
            )}
          </Field>
        </div>
      </div>

      {/* Eligibility */}
      <div>
        <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.12em] text-ink-500 dark:text-ink-300">
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
      </div>
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
      <p className="text-sm text-ink-500 dark:text-ink-400">
        Define aliases for upload columns and override component flags without changing ComponentConfig.
      </p>

      <div className="overflow-x-auto rounded-xl border border-ink-200/70 dark:border-white/10">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-ink-50/80 text-[11px] uppercase tracking-[0.12em] text-ink-500 dark:bg-white/[0.03] dark:text-ink-300">
              {["Upload column", "Component name", "PF", "ESIC", "In wages", "Taxable", ""].map((h) => (
                <th key={h} className="px-3 py-2 text-left font-semibold">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-100 dark:divide-white/[0.05]">
            {cfg.entries.map((e, i) => (
              <tr key={i} className="hover:bg-ink-50/40 dark:hover:bg-white/[0.03]">
                <td className="px-3 py-2">
                  <input
                    type="text"
                    value={e.upload_column}
                    placeholder="column_name"
                    className="w-28 rounded border border-ink-200 bg-white px-2 py-1 text-xs text-ink-900 dark:border-white/10 dark:bg-white/[0.04] dark:text-white"
                    onChange={(ev) => updateEntry(i, "upload_column", ev.target.value)}
                  />
                </td>
                <td className="px-3 py-2">
                  <input
                    type="text"
                    value={e.component_name}
                    placeholder="Component"
                    className="w-28 rounded border border-ink-200 bg-white px-2 py-1 text-xs text-ink-900 dark:border-white/10 dark:bg-white/[0.04] dark:text-white"
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
                    className="text-danger-400 transition-colors hover:text-danger-600 dark:text-danger-400 dark:hover:text-danger-300"
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
        className="inline-flex items-center gap-1.5 rounded-xl border border-brand-200 px-3 py-1.5 text-xs font-semibold text-brand-600 transition-colors hover:bg-brand-50 dark:border-brand-500/30 dark:text-brand-300 dark:hover:bg-brand-500/15"
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

export default function StatutoryConfigPage() {
  const [cfg, setCfg] = useState<TenantStatutoryConfig>({
    pf: defaultPFConfig,
    esic: defaultESICConfig,
    component_mapping: { entries: [], ignore_columns: [] },
  });
  const [loading, setLoading]   = useState(true);
  const [saving,  setSaving]    = useState(false);
  const [saved,   setSaved]     = useState(false);
  const [error,   setError]     = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    getStatutoryConfig()
      .then(data => {
        setCfg({ pf: data.pf, esic: data.esic, component_mapping: data.component_mapping });
        setUpdatedAt(data.updated_at);
      })
      .catch(() => { /* use defaults */ })
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true); setError(null); setSaved(false);
    try {
      const data = await saveStatutoryConfig(cfg);
      setUpdatedAt(data.updated_at);
      setSaved(true);
      toast.success("Statutory configuration saved", {
        description: "The next validation run will use these settings.",
      });
      setTimeout(() => setSaved(false), 3200);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    if (!confirm("Reset to India statutory defaults? This will overwrite your current config.")) return;
    setSaving(true);
    try {
      const data = await resetStatutoryConfig();
      setCfg({ pf: data.pf, esic: data.esic, component_mapping: data.component_mapping });
      setUpdatedAt(data.updated_at);
      toast.success("Defaults restored", { description: "PF, ESIC, and mapping reset to India statutory baseline." });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Reset failed");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-2">
            <Skeleton className="h-8 w-72" />
            <Skeleton className="h-4 w-full max-w-lg" />
            <Skeleton className="h-3 w-48" />
          </div>
          <div className="flex gap-2">
            <Skeleton className="h-10 w-36 rounded-xl" />
            <Skeleton className="h-10 w-36 rounded-xl" />
          </div>
        </div>
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-52 w-full rounded-2xl" />
        ))}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <PageHeader
        title="Statutory configuration"
        eyebrow="Statutory engine"
        description={
          <>
            Tenant-scoped PF & ESIC engine: rates, wage rules, rounding, eligibility expressions, and upload
            column overrides.
            {updatedAt ? (
              <span className="mt-2 block text-xs font-medium uppercase tracking-wide text-ink-400 dark:text-ink-500">
                Last saved · {new Date(updatedAt).toLocaleString("en-IN")}
              </span>
            ) : null}
          </>
        }
        actions={
          <>
            <Button variant="outline" type="button" onClick={handleReset} disabled={saving}>
              <RefreshCw size={15} strokeWidth={2} /> Reset
            </Button>
            <Button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className={`min-w-[8.5rem] ${saved ? "!from-success-600 !to-success-500" : ""}`}
            >
              {saving ? <RefreshCw size={15} strokeWidth={2} className="animate-spin" /> : null}
              {!saving && saved ? <CheckCircle2 size={15} strokeWidth={2} /> : null}
              {!saving && !saved ? <Save size={15} strokeWidth={2} /> : null}
              {saving ? "Saving…" : saved ? "Saved" : "Save"}
            </Button>
          </>
        }
      />

      {error ? (
        <AlertBanner variant="error" title="Unable to save or load">
          {error}
        </AlertBanner>
      ) : null}

      {saved ? (
        <AlertBanner variant="success" title="Configuration updated">
          Your PF, ESIC, and mapping changes are stored. Running validations will pick them up automatically.
        </AlertBanner>
      ) : null}

      <AlertBanner variant="info">
        All changes here take effect on the <strong>next validation run</strong>. Expressions run in a safe sandbox —
        no imports or shell access. Each tenant&apos;s config is isolated.
      </AlertBanner>

      {/* PF */}
      <Section title="Provident Fund (PF)" icon={<Shield size={16} className="text-brand-500" />}>
        {/* Quick summary */}
        <div className="mb-5 flex flex-wrap gap-2">
          {[
            { label: "Emp rate", val: pct(cfg.pf.rates.employee_rate) },
            { label: "Er rate", val: pct(cfg.pf.rates.employer_rate) },
            { label: "EPS", val: pct(cfg.pf.rates.eps_rate) },
            {
              label: "Ceiling",
              val: `₹${parseInt(cfg.pf.wage.wage_ceiling).toLocaleString("en-IN")}`,
            },
            { label: "Restricted", val: cfg.pf.wage.restrict_to_ceiling ? "Yes" : "No" },
          ].map((s) => (
            <div
              key={s.label}
              className="rounded-lg border border-brand-200/60 bg-brand-50 px-3 py-1.5 text-xs dark:border-brand-500/30 dark:bg-brand-500/10"
            >
              <span className="text-brand-700 dark:text-brand-300">{s.label}: </span>
              <span className="font-semibold text-brand-900 dark:text-brand-100">{s.val}</span>
            </div>
          ))}
        </div>
        <PFConfigPanel cfg={cfg.pf} onChange={(pf) => setCfg((c) => ({ ...c, pf }))} />
      </Section>

      {/* ESIC */}
      <Section
        title="Employee State Insurance (ESIC)"
        icon={<Shield size={16} className="text-success-500 dark:text-success-400" />}
      >
        <div className="mb-5 flex flex-wrap gap-2">
          {[
            { label: "Emp rate", val: pct(cfg.esic.rates.employee_rate) },
            { label: "Er rate", val: pct(cfg.esic.rates.employer_rate) },
            {
              label: "Ceiling",
              val: `₹${parseInt(cfg.esic.wage.wage_ceiling).toLocaleString("en-IN")}`,
            },
            { label: "Rounding", val: cfg.esic.rounding.mode },
          ].map((s) => (
            <div
              key={s.label}
              className="rounded-lg border border-success-200/60 bg-success-50 px-3 py-1.5 text-xs dark:border-success-500/30 dark:bg-success-500/10"
            >
              <span className="text-success-700 dark:text-success-300">{s.label}: </span>
              <span className="font-semibold text-success-800 dark:text-success-100">{s.val}</span>
            </div>
          ))}
        </div>
        <ESICConfigPanel cfg={cfg.esic} onChange={(esic) => setCfg((c) => ({ ...c, esic }))} />
      </Section>

      {/* Component mapping */}
      <Section
        title="Component mapping overrides"
        icon={<Settings2 size={16} className="text-ink-500 dark:text-ink-300" />}
        defaultOpen={false}
      >
        <ComponentMappingPanel
          cfg={cfg.component_mapping}
          onChange={(component_mapping) => setCfg((c) => ({ ...c, component_mapping }))}
        />
      </Section>
    </div>
  );
}
