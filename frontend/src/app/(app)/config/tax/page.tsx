"use client";

import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/layout/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import {
  Landmark, SlidersHorizontal, ChevronDown, ChevronUp, Plus, Trash2,
  Save, RefreshCw, Star, Calculator, ToggleLeft, ToggleRight,
} from "lucide-react";
import {
  type IncomeTaxConfig, type TaxYearConfig, type RegimeConfig, type TaxSlab,
  type SurchargeBracket, type RuleThresholdsConfig, type RegimeComparison,
  getIncomeTaxConfig, upsertTaxYear, deleteTaxYear, resetIncomeTaxConfig,
  getRuleThresholds, saveRuleThresholds, resetRuleThresholds,
  compareRegimes,
} from "@/lib/statutory-config";

// ─── small helpers (visual language shared with config/statutory) ────────────

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

const inputCls =
  "w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900 shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-brand-500/40 dark:border-white/10 dark:bg-white/[0.04] dark:text-white";

function NumInput({ value, onChange, step = "any", placeholder }: {
  value: string; onChange: (v: string) => void; step?: string; placeholder?: string;
}) {
  return (
    <input type="number" value={value} step={step} placeholder={placeholder}
      className={inputCls} onChange={(e) => onChange(e.target.value)} />
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

// fraction <-> percent display helpers
const toPct = (frac: string) => {
  const f = parseFloat(frac);
  return Number.isFinite(f) ? String(parseFloat((f * 100).toFixed(6))) : "";
};
const fromPct = (pct: string) => {
  const p = parseFloat(pct);
  return Number.isFinite(p) ? String(parseFloat((p / 100).toFixed(8))) : "0";
};

// ─── slab / bracket table editor ─────────────────────────────────────────────

function BandTable<T extends { up_to: string | null; rate: string }>({
  rows, onChange, upToLabel, rateLabel,
}: {
  rows: T[]; onChange: (rows: T[]) => void; upToLabel: string; rateLabel: string;
}) {
  const update = (i: number, patch: Partial<T>) => {
    const next = rows.slice();
    next[i] = { ...next[i], ...patch };
    onChange(next);
  };
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] font-bold uppercase tracking-[0.12em] text-ink-500 dark:text-ink-400">
            <th className="pb-2 pr-3">{upToLabel}</th>
            <th className="pb-2 pr-3">{rateLabel}</th>
            <th className="pb-2 w-10" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-ink-100 dark:border-white/[0.06]">
              <td className="py-2 pr-3">
                {row.up_to === null ? (
                  <span className="inline-flex items-center rounded-lg bg-ink-100 px-3 py-2 text-xs font-semibold text-ink-600 dark:bg-white/[0.06] dark:text-ink-300">
                    No upper bound (∞)
                  </span>
                ) : (
                  <NumInput value={row.up_to} onChange={(v) => update(i, { up_to: v } as Partial<T>)} />
                )}
              </td>
              <td className="py-2 pr-3">
                <NumInput value={toPct(row.rate)} onChange={(v) => update(i, { rate: fromPct(v) } as Partial<T>)} />
              </td>
              <td className="py-2 text-right">
                <button
                  className="rounded-lg p-1.5 text-ink-400 transition-colors hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-500/10"
                  onClick={() => onChange(rows.filter((_, j) => j !== i))}
                  title="Remove band"
                >
                  <Trash2 size={14} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2">
        <Button
          variant="outline" size="sm"
          onClick={() => {
            const last = rows[rows.length - 1];
            const insertAt = last && last.up_to === null ? rows.length - 1 : rows.length;
            const next = rows.slice();
            next.splice(insertAt, 0, { up_to: "0", rate: "0" } as T);
            onChange(next);
          }}
        >
          <Plus size={14} className="mr-1" /> Add band
        </Button>
      </div>
    </div>
  );
}

// ─── regime editor ────────────────────────────────────────────────────────────

function RegimeEditor({ regime, onChange, showChapterVia }: {
  regime: RegimeConfig; onChange: (r: RegimeConfig) => void; showChapterVia?: boolean;
}) {
  return (
    <div className="flex flex-col gap-5">
      <div>
        <p className="mb-2 text-[11px] font-bold uppercase tracking-[0.12em] text-ink-600 dark:text-ink-300">
          Tax slabs (₹ upper bound → rate %)
        </p>
        <BandTable rows={regime.slabs}
          onChange={(slabs) => onChange({ ...regime, slabs: slabs as TaxSlab[] })}
          upToLabel="Taxable income up to (₹)" rateLabel="Rate (%)" />
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Standard deduction (₹)">
          <NumInput value={regime.standard_deduction}
            onChange={(v) => onChange({ ...regime, standard_deduction: v })} />
        </Field>
        <Field label="87A rebate up to taxable (₹)" help="0 disables the rebate">
          <NumInput value={regime.rebate.taxable_income_limit}
            onChange={(v) => onChange({ ...regime, rebate: { ...regime.rebate, taxable_income_limit: v } })} />
        </Field>
        <Field label="Max rebate (₹)">
          <NumInput value={regime.rebate.max_rebate}
            onChange={(v) => onChange({ ...regime, rebate: { ...regime.rebate, max_rebate: v } })} />
        </Field>
      </div>
      <div className="flex flex-wrap items-center gap-6">
        <Toggle checked={regime.rebate.marginal_relief} label="Marginal relief at rebate threshold"
          onChange={(v) => onChange({ ...regime, rebate: { ...regime.rebate, marginal_relief: v } })} />
        {showChapterVia && (
          <Toggle checked={regime.allow_chapter_via} label="Chapter VI-A deductions apply"
            onChange={(v) => onChange({ ...regime, allow_chapter_via: v })} />
        )}
      </div>
      <div>
        <p className="mb-2 text-[11px] font-bold uppercase tracking-[0.12em] text-ink-600 dark:text-ink-300">
          Surcharge brackets (taxable income → % of tax)
        </p>
        <BandTable rows={regime.surcharge_brackets}
          onChange={(b) => onChange({ ...regime, surcharge_brackets: b as SurchargeBracket[] })}
          upToLabel="Taxable income up to (₹)" rateLabel="Surcharge (%)" />
      </div>
    </div>
  );
}

// ─── page ─────────────────────────────────────────────────────────────────────

export default function TaxConfigPage() {
  const [cfg, setCfg] = useState<IncomeTaxConfig | null>(null);
  const [thresholds, setThresholds] = useState<RuleThresholdsConfig | null>(null);
  const [selectedYear, setSelectedYear] = useState<string>("");
  const [savingYear, setSavingYear] = useState(false);
  const [savingThresholds, setSavingThresholds] = useState(false);
  const [tryGross, setTryGross] = useState("1500000");
  const [comparison, setComparison] = useState<RegimeComparison | null>(null);

  const load = async () => {
    try {
      const [tax, thr] = await Promise.all([getIncomeTaxConfig(), getRuleThresholds()]);
      setCfg(tax);
      setThresholds(thr);
      setSelectedYear((prev) => (prev && tax.years[prev] ? prev : tax.default_year || Object.keys(tax.years)[0] || ""));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to load tax configuration");
    }
  };

  useEffect(() => { load(); }, []);

  const year = useMemo(
    () => (cfg && selectedYear ? cfg.years[selectedYear] : null),
    [cfg, selectedYear],
  );

  const patchYear = (patch: Partial<TaxYearConfig>) => {
    if (!cfg || !year) return;
    setCfg({ ...cfg, years: { ...cfg.years, [selectedYear]: { ...year, ...patch } } });
  };

  const saveYear = async () => {
    if (!cfg || !year) return;
    setSavingYear(true);
    try {
      const next = await upsertTaxYear(selectedYear, year);
      setCfg(next);
      toast.success(`FY ${selectedYear} saved`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSavingYear(false);
    }
  };

  const addYear = async () => {
    if (!cfg || !year) return;
    const [startStr] = selectedYear.split("-");
    const start = parseInt(startStr, 10);
    const label = Number.isFinite(start)
      ? `${start + 1}-${String(start + 2).slice(-2)}`
      : `${selectedYear}-copy`;
    if (cfg.years[label]) {
      toast.error(`FY ${label} already exists`);
      return;
    }
    try {
      const next = await upsertTaxYear(label, { ...year, financial_year: label, notes: `Copied from FY ${selectedYear}.` });
      setCfg(next);
      setSelectedYear(label);
      toast.success(`FY ${label} created from ${selectedYear} — adjust and save`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not add year");
    }
  };

  const removeYear = async () => {
    if (!cfg || Object.keys(cfg.years).length <= 1) return;
    if (!window.confirm(`Delete FY ${selectedYear} configuration?`)) return;
    try {
      const next = await deleteTaxYear(selectedYear);
      setCfg(next);
      setSelectedYear(next.default_year || Object.keys(next.years)[0]);
      toast.success(`FY ${selectedYear} removed`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not delete year");
    }
  };

  const makeDefault = async () => {
    if (!cfg || !year) return;
    try {
      const next = await upsertTaxYear(selectedYear, year, true);
      setCfg(next);
      toast.success(`FY ${selectedYear} is now the default`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not set default");
    }
  };

  const resetTax = async () => {
    if (!window.confirm("Reset income tax configuration to seeded defaults? Custom years will be removed.")) return;
    try {
      const next = await resetIncomeTaxConfig();
      setCfg(next);
      setSelectedYear(next.default_year);
      toast.success("Income tax configuration reset to defaults");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Reset failed");
    }
  };

  const saveThresholdsNow = async () => {
    if (!thresholds) return;
    setSavingThresholds(true);
    try {
      setThresholds(await saveRuleThresholds(thresholds));
      toast.success("Rule thresholds saved");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSavingThresholds(false);
    }
  };

  const resetThresholdsNow = async () => {
    if (!window.confirm("Reset all rule thresholds to defaults?")) return;
    try {
      setThresholds(await resetRuleThresholds());
      toast.success("Rule thresholds reset");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Reset failed");
    }
  };

  const runComparison = async () => {
    const gross = parseFloat(tryGross);
    if (!Number.isFinite(gross) || gross <= 0) {
      toast.error("Enter a valid annual gross");
      return;
    }
    try {
      setComparison(await compareRegimes(gross, selectedYear));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Comparison failed");
    }
  };

  if (!cfg || !thresholds) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title="Income tax & thresholds" description="FY-versioned statutory parameters — nothing is hardcoded" />
        <Skeleton className="h-40 w-full rounded-2xl" />
        <Skeleton className="h-64 w-full rounded-2xl" />
      </div>
    );
  }

  const yearKeys = Object.keys(cfg.years).sort();

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Income tax & thresholds"
        description="Every slab, rebate, surcharge, cess and rule threshold is data — editable per financial year"
      />

      {/* FY picker */}
      <div className="flex flex-wrap items-center gap-2">
        {yearKeys.map((fy) => (
          <button
            key={fy}
            onClick={() => setSelectedYear(fy)}
            className={`inline-flex items-center gap-1.5 rounded-full border px-4 py-1.5 text-sm font-semibold transition-colors ${
              fy === selectedYear
                ? "border-brand-500 bg-brand-50 text-brand-700 dark:border-brand-400/50 dark:bg-brand-500/10 dark:text-brand-300"
                : "border-ink-200 bg-white text-ink-600 hover:border-ink-300 dark:border-white/10 dark:bg-white/[0.04] dark:text-ink-300"
            }`}
          >
            {fy === cfg.default_year && <Star size={12} className="fill-current" />}
            FY {fy}
          </button>
        ))}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={addYear}>
            <Plus size={14} className="mr-1" /> Add next FY
          </Button>
          {selectedYear !== cfg.default_year && (
            <Button variant="outline" size="sm" onClick={makeDefault}>
              <Star size={14} className="mr-1" /> Make default
            </Button>
          )}
          {yearKeys.length > 1 && (
            <Button variant="outline" size="sm" onClick={removeYear}>
              <Trash2 size={14} className="mr-1" /> Delete FY
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={resetTax}>
            <RefreshCw size={14} className="mr-1" /> Reset to defaults
          </Button>
        </div>
      </div>

      {year && (
        <>
          <Section title={`New regime — FY ${selectedYear}`} icon={<Landmark size={16} className="text-brand-600 dark:text-brand-300" />}>
            <RegimeEditor regime={year.new_regime} onChange={(r) => patchYear({ new_regime: r })} />
          </Section>

          <Section title={`Old regime — FY ${selectedYear}`} icon={<Landmark size={16} className="text-brand-600 dark:text-brand-300" />} defaultOpen={false}>
            <div className="flex flex-col gap-5">
              <RegimeEditor regime={year.old_regime} onChange={(r) => patchYear({ old_regime: r })} showChapterVia />
              <div>
                <p className="mb-2 text-[11px] font-bold uppercase tracking-[0.12em] text-ink-600 dark:text-ink-300">
                  Chapter VI-A caps (₹)
                </p>
                <div className="grid gap-4 sm:grid-cols-4">
                  <Field label="80C">
                    <NumInput value={year.deduction_caps.section_80c}
                      onChange={(v) => patchYear({ deduction_caps: { ...year.deduction_caps, section_80c: v } })} />
                  </Field>
                  <Field label="80D (combined)">
                    <NumInput value={year.deduction_caps.section_80d}
                      onChange={(v) => patchYear({ deduction_caps: { ...year.deduction_caps, section_80d: v } })} />
                  </Field>
                  <Field label="80CCD(1B)">
                    <NumInput value={year.deduction_caps.section_80ccd_1b}
                      onChange={(v) => patchYear({ deduction_caps: { ...year.deduction_caps, section_80ccd_1b: v } })} />
                  </Field>
                  <Field label="Home loan interest 24(b)">
                    <NumInput value={year.deduction_caps.home_loan_interest}
                      onChange={(v) => patchYear({ deduction_caps: { ...year.deduction_caps, home_loan_interest: v } })} />
                  </Field>
                </div>
              </div>
            </div>
          </Section>

          <Section title="Cess & notes" defaultOpen={false}>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Health & education cess (%)">
                <NumInput value={toPct(year.cess_rate)} onChange={(v) => patchYear({ cess_rate: fromPct(v) })} />
              </Field>
              <Field label="Notes / provenance">
                <input type="text" value={year.notes} className={inputCls}
                  onChange={(e) => patchYear({ notes: e.target.value })} />
              </Field>
            </div>
          </Section>

          <div className="flex items-center gap-3">
            <Button onClick={saveYear} disabled={savingYear}>
              <Save size={15} className="mr-1.5" /> {savingYear ? "Saving…" : `Save FY ${selectedYear}`}
            </Button>
          </div>

          {/* Quick regime comparison against current (unsaved changes excluded) */}
          <Section title="Try it — old vs new regime" icon={<Calculator size={16} className="text-brand-600 dark:text-brand-300" />} defaultOpen={false}>
            <div className="flex flex-col gap-4">
              <div className="flex flex-wrap items-end gap-3">
                <div className="w-56">
                  <Field label="Annual gross (₹)">
                    <NumInput value={tryGross} onChange={setTryGross} />
                  </Field>
                </div>
                <Button variant="outline" onClick={runComparison}>Compare (saved config)</Button>
              </div>
              {comparison && (
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-xl border border-ink-200/70 p-4 dark:border-white/[0.07]">
                    <p className="text-xs font-bold uppercase tracking-wide text-ink-500 dark:text-ink-400">Old regime</p>
                    <p className="mt-1 text-lg font-semibold text-ink-900 dark:text-white">₹{comparison.old.total_tax_annual.toLocaleString("en-IN")}</p>
                    <p className="text-xs text-ink-500 dark:text-ink-400">TDS ₹{comparison.old.monthly_tds.toLocaleString("en-IN")}/month</p>
                  </div>
                  <div className="rounded-xl border border-ink-200/70 p-4 dark:border-white/[0.07]">
                    <p className="text-xs font-bold uppercase tracking-wide text-ink-500 dark:text-ink-400">New regime</p>
                    <p className="mt-1 text-lg font-semibold text-ink-900 dark:text-white">₹{comparison.new.total_tax_annual.toLocaleString("en-IN")}</p>
                    <p className="text-xs text-ink-500 dark:text-ink-400">TDS ₹{comparison.new.monthly_tds.toLocaleString("en-IN")}/month</p>
                  </div>
                  <div className="rounded-xl border border-brand-300/60 bg-brand-50/60 p-4 dark:border-brand-400/30 dark:bg-brand-500/10">
                    <p className="text-xs font-bold uppercase tracking-wide text-brand-700 dark:text-brand-300">Cheaper: {comparison.cheaper_regime} regime</p>
                    <p className="mt-1 text-lg font-semibold text-brand-800 dark:text-brand-200">saves ₹{comparison.annual_saving.toLocaleString("en-IN")}</p>
                    <p className="text-xs text-brand-700/80 dark:text-brand-300/80">FY {comparison.financial_year}</p>
                  </div>
                </div>
              )}
            </div>
          </Section>
        </>
      )}

      {/* Rule thresholds */}
      <Section title="Validation rule thresholds" icon={<SlidersHorizontal size={16} className="text-brand-600 dark:text-brand-300" />} defaultOpen={false}>
        <div className="flex flex-col gap-5">
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Min PF wage % of gross" help="STRUCT-001: below this flags PF avoidance">
              <NumInput value={thresholds.structural.min_pf_wage_pct_of_gross}
                onChange={(v) => setThresholds({ ...thresholds, structural: { ...thresholds.structural, min_pf_wage_pct_of_gross: v } })} />
            </Field>
            <Field label="Recommended PF wage %" help="Used in suggested fixes and impact estimates">
              <NumInput value={thresholds.structural.recommended_pf_wage_pct}
                onChange={(v) => setThresholds({ ...thresholds, structural: { ...thresholds.structural, recommended_pf_wage_pct: v } })} />
            </Field>
            <Field label="Allowance-heavy % of gross" help="STRUCT-002: above this flags allowance-heavy mix">
              <NumInput value={thresholds.structural.allowance_heavy_pct}
                onChange={(v) => setThresholds({ ...thresholds, structural: { ...thresholds.structural, allowance_heavy_pct: v } })} />
            </Field>
            <Field label="Gross mismatch tolerance (₹)" help="AGG-001">
              <NumInput value={thresholds.tolerances.gross_mismatch}
                onChange={(v) => setThresholds({ ...thresholds, tolerances: { ...thresholds.tolerances, gross_mismatch: v } })} />
            </Field>
            <Field label="Net mismatch tolerance (₹)" help="AGG-002">
              <NumInput value={thresholds.tolerances.net_mismatch}
                onChange={(v) => setThresholds({ ...thresholds, tolerances: { ...thresholds.tolerances, net_mismatch: v } })} />
            </Field>
            <Field label="Statutory mismatch tolerance (₹)" help="PF / ESIC / PT / LWF checks">
              <NumInput value={thresholds.tolerances.statutory_mismatch}
                onChange={(v) => setThresholds({ ...thresholds, tolerances: { ...thresholds.tolerances, statutory_mismatch: v } })} />
            </Field>
            <Field label="Component change % (MoM)" help="MOM-002 / MOM-003 spike or drop">
              <NumInput value={thresholds.trends.component_change_pct}
                onChange={(v) => setThresholds({ ...thresholds, trends: { ...thresholds.trends, component_change_pct: v } })} />
            </Field>
            <Field label="Salary spike ratio" help="ADV-002: gross > × prior month">
              <NumInput value={thresholds.trends.salary_spike_ratio}
                onChange={(v) => setThresholds({ ...thresholds, trends: { ...thresholds.trends, salary_spike_ratio: v } })} />
            </Field>
            <Field label="Salary drop ratio" help="ADV-003: gross < fraction of prior month">
              <NumInput value={thresholds.trends.salary_drop_ratio}
                onChange={(v) => setThresholds({ ...thresholds, trends: { ...thresholds.trends, salary_drop_ratio: v } })} />
            </Field>
            <Field label="TDS risk annual income (₹)" help="STAT-011 heuristic threshold">
              <NumInput value={thresholds.tds.annual_income_threshold}
                onChange={(v) => setThresholds({ ...thresholds, tds: { ...thresholds.tds, annual_income_threshold: v } })} />
            </Field>
            <Field label="Arrear annualisation factor" help="Fraction of arrears counted in the month">
              <NumInput value={thresholds.tds.arrear_annualisation_factor}
                onChange={(v) => setThresholds({ ...thresholds, tds: { ...thresholds.tds, arrear_annualisation_factor: v } })} />
            </Field>
            <Field label="Gratuity exemption cap (₹)" help="STAT-014">
              <NumInput value={thresholds.gratuity.exemption_cap}
                onChange={(v) => setThresholds({ ...thresholds, gratuity: { ...thresholds.gratuity, exemption_cap: v } })} />
            </Field>
          </div>
          <div className="flex items-center gap-3">
            <Button onClick={saveThresholdsNow} disabled={savingThresholds}>
              <Save size={15} className="mr-1.5" /> {savingThresholds ? "Saving…" : "Save thresholds"}
            </Button>
            <Button variant="outline" onClick={resetThresholdsNow}>
              <RefreshCw size={14} className="mr-1" /> Reset to defaults
            </Button>
          </div>
        </div>
      </Section>
    </div>
  );
}
