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
    <div className="overflow-hidden rounded-2xl border border-slate-200/90 bg-white shadow-soft ring-1 ring-slate-900/[0.04]">
      <button
        className="flex w-full items-center justify-between px-5 py-4 text-left transition-colors hover:bg-slate-50"
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex items-center gap-2">
          {icon}
          <span className="font-semibold text-slate-800 text-sm">{title}</span>
        </div>
        {open ? <ChevronUp size={16} className="text-slate-400"/> : <ChevronDown size={16} className="text-slate-400"/>}
      </button>
      {open && <div className="px-5 pb-5 border-t border-slate-100 pt-4">{children}</div>}
    </div>
  );
}

function Field({ label, help, children }: { label: string; help?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-semibold text-slate-600 uppercase tracking-wide">{label}</label>
      {children}
      {help && <p className="text-xs text-slate-400">{help}</p>}
    </div>
  );
}

function NumberInput({ value, onChange, step = "0.0001", min = "0", max = "1" }: {
  value: string; onChange: (v: string) => void;
  step?: string; min?: string; max?: string;
}) {
  return (
    <input type="number" value={value} step={step} min={min} max={max}
      className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-brand-500/25"
      onChange={e => onChange(e.target.value)}
    />
  );
}

function TextInput({ value, onChange, placeholder = "" }: {
  value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  return (
    <input type="text" value={value} placeholder={placeholder}
      className="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-brand-500/25"
      onChange={e => onChange(e.target.value)}
    />
  );
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <button onClick={() => onChange(!checked)}
      className={`inline-flex items-center gap-2 text-sm font-medium transition-colors
        ${checked ? "text-brand-700" : "text-slate-500"}`}
    >
      {checked ? <ToggleRight size={20} className="text-brand-600"/> : <ToggleLeft size={20} className="text-slate-400"/>}
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
    if (v && !values.includes(v)) { onChange([...values, v]); setInput(""); }
  };
  return (
    <div className="flex flex-wrap gap-1.5">
      {values.map(v => (
        <span key={v} className="inline-flex items-center gap-1 px-2 py-0.5 bg-brand-100 text-brand-700 text-xs rounded-full font-medium">
          {v}
          <button onClick={() => onChange(values.filter(x => x !== v))}><Trash2 size={10}/></button>
        </span>
      ))}
      <input
        className="text-sm border border-dashed border-slate-300 rounded px-2 py-0.5 focus:outline-none focus:border-brand-400 min-w-24"
        placeholder={placeholder || "Add…"}
        value={input}
        onChange={e => setInput(e.target.value)}
        onKeyDown={e => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); }}}
      />
      <button onClick={add} className="text-brand-600 hover:text-brand-800"><Plus size={14}/></button>
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
    <div className="flex items-center gap-3 mt-2">
      <button
        onClick={run}
        disabled={running}
        className="inline-flex items-center gap-1.5 rounded-lg bg-brand-50 px-3 py-1.5 text-xs font-medium text-brand-700 hover:bg-brand-100 disabled:opacity-50"
      >
        <Beaker size={12}/> {running ? "Testing…" : "Test expression"}
      </button>
      {result && (
        <span className={`text-xs font-mono ${result.startsWith("✓") ? "text-green-700" : "text-red-600"}`}>
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
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Contribution Rates</p>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          {(["employee_rate","employer_rate","eps_rate","edli_rate","admin_rate"] as const).map(k => (
            <Field key={k} label={k.replace("_rate","").toUpperCase()} help={pct(cfg.rates[k])}>
              <NumberInput value={cfg.rates[k]} onChange={v => setRates(k, v)}/>
            </Field>
          ))}
        </div>
      </div>

      {/* Wage */}
      <div>
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">PF Wage Computation</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Above-Ceiling Contributions</p>
        <select
          value={cfg.above_ceiling_mode}
          onChange={e => set("above_ceiling_mode", e.target.value as PFConfig["above_ceiling_mode"])}
          className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-brand-500/25"
        >
          <option value="none">None — always cap at ceiling</option>
          <option value="employee_choice">Employee choice — voluntary above ceiling</option>
          <option value="employer_choice">Employer choice — employer contributes on full wage</option>
        </select>
      </div>

      {/* Voluntary PF */}
      <div>
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Voluntary PF</p>
        <Toggle checked={cfg.voluntary.enabled} onChange={v => setVol("enabled", v)} label="Enable Voluntary PF components"/>
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
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">PF Eligibility</p>
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
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Contribution Rates</p>
        <div className="grid grid-cols-2 gap-3 max-w-xs">
          <Field label="Employee" help={pct(cfg.rates.employee_rate)}>
            <NumberInput value={cfg.rates.employee_rate} onChange={v => setRates("employee_rate", v)}/>
          </Field>
          <Field label="Employer" help={pct(cfg.rates.employer_rate)}>
            <NumberInput value={cfg.rates.employer_rate} onChange={v => setRates("employer_rate", v)}/>
          </Field>
        </div>
      </div>

      {/* Wage */}
      <div>
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">ESIC Wage Computation</p>
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
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Rounding</p>
        <div className="flex items-center gap-4">
          {(["up","down","nearest"] as const).map(m => (
            <label key={m} className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="radio" name="esic_round" value={m} checked={cfg.rounding.mode === m}
                onChange={() => setRound("mode", m)} className="accent-brand-600"/>
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
        <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Eligibility & Entry/Exit</p>
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
      <p className="text-sm text-slate-500">
        Define aliases for upload columns and override component flags without changing ComponentConfig.
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-slate-50 text-slate-500 uppercase tracking-wide">
              {["Upload Column","Component Name","PF","ESIC","In Wages","Taxable",""].map(h=>(
                <th key={h} className="px-3 py-2 text-left font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {cfg.entries.map((e, i) => (
              <tr key={i}>
                <td className="px-3 py-2"><input type="text" value={e.upload_column} placeholder="column_name"
                  className="w-28 px-2 py-1 border border-slate-200 rounded text-xs"
                  onChange={ev => updateEntry(i, "upload_column", ev.target.value)}/></td>
                <td className="px-3 py-2"><input type="text" value={e.component_name} placeholder="Component"
                  className="w-28 px-2 py-1 border border-slate-200 rounded text-xs"
                  onChange={ev => updateEntry(i, "component_name", ev.target.value)}/></td>
                {(["pf_applicable","esic_applicable","included_in_wages","taxable"] as const).map(k => (
                  <td key={k} className="px-3 py-2 text-center">
                    <input type="checkbox" checked={e[k]} className="accent-brand-600"
                      onChange={ev => updateEntry(i, k, ev.target.checked)}/>
                  </td>
                ))}
                <td className="px-3 py-2">
                  <button onClick={() => removeEntry(i)} className="text-red-400 hover:text-red-600"><Trash2 size={12}/></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <button onClick={addEntry}
        className="inline-flex items-center gap-1.5 rounded-xl border border-brand-200 px-3 py-1.5 text-xs font-medium text-brand-600 hover:bg-brand-50">
        <Plus size={12}/> Add alias
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
        description={
          <>
            Tenant-scoped PF & ESIC engine: rates, wage rules, rounding, eligibility expressions, and upload column overrides.
            {updatedAt ? (
              <span className="mt-2 block text-xs font-medium uppercase tracking-wide text-slate-400">
                Last saved · {new Date(updatedAt).toLocaleString("en-IN")}
              </span>
            ) : null}
          </>
        }
        actions={
          <>
            <Button
              variant="outline"
              type="button"
              onClick={handleReset}
              disabled={saving}
              className="rounded-xl border-slate-200 bg-white shadow-sm"
            >
              <RefreshCw size={15} strokeWidth={2} /> Reset
            </Button>
            <Button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className={`min-w-[8.5rem] rounded-xl shadow-soft ${
                saved ? "bg-emerald-600 hover:bg-emerald-700" : ""
              }`}
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
      <Section title="Provident Fund (PF)" icon={<Shield size={16} className="text-brand-500"/>}>
        {/* Quick summary */}
        <div className="flex flex-wrap gap-3 mb-5">
          {[
            { label: "Emp rate", val: pct(cfg.pf.rates.employee_rate) },
            { label: "Emp&apos;r rate", val: pct(cfg.pf.rates.employer_rate) },
            { label: "EPS", val: pct(cfg.pf.rates.eps_rate) },
            { label: "Ceiling", val: `₹${parseInt(cfg.pf.wage.wage_ceiling).toLocaleString("en-IN")}` },
            { label: "Restricted", val: cfg.pf.wage.restrict_to_ceiling ? "Yes" : "No" },
          ].map(s => (
            <div key={s.label} className="rounded-lg border border-brand-100 bg-brand-50 px-3 py-1.5 text-xs">
              <span className="text-brand-600">{s.label}: </span>
              <span className="font-semibold text-brand-900">{s.val}</span>
            </div>
          ))}
        </div>
        <PFConfigPanel cfg={cfg.pf} onChange={pf => setCfg(c => ({ ...c, pf }))}/>
      </Section>

      {/* ESIC */}
      <Section title="Employee State Insurance (ESIC)" icon={<Shield size={16} className="text-green-500"/>}>
        <div className="flex flex-wrap gap-3 mb-5">
          {[
            { label: "Emp rate", val: pct(cfg.esic.rates.employee_rate) },
            { label: "Emp&apos;r rate", val: pct(cfg.esic.rates.employer_rate) },
            { label: "Ceiling", val: `₹${parseInt(cfg.esic.wage.wage_ceiling).toLocaleString("en-IN")}` },
            { label: "Rounding", val: cfg.esic.rounding.mode },
          ].map(s => (
            <div key={s.label} className="bg-green-50 border border-green-100 rounded-lg px-3 py-1.5 text-xs">
              <span className="text-green-500">{s.label}: </span>
              <span className="font-semibold text-green-800">{s.val}</span>
            </div>
          ))}
        </div>
        <ESICConfigPanel cfg={cfg.esic} onChange={esic => setCfg(c => ({ ...c, esic }))}/>
      </Section>

      {/* Component mapping */}
      <Section title="Component Mapping Overrides" icon={<Settings2 size={16} className="text-slate-500"/>} defaultOpen={false}>
        <ComponentMappingPanel
          cfg={cfg.component_mapping}
          onChange={component_mapping => setCfg(c => ({ ...c, component_mapping }))}
        />
      </Section>
    </div>
  );
}
