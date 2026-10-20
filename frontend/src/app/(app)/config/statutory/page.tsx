"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { EmployeeFormula } from "@/components/config/EmployeeFormula";
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
import { RefreshCw, ToggleLeft, ToggleRight } from "lucide-react";
import { MinimumWagePanel } from "@/components/config/MinimumWagePanel";
import { SlabsPanel } from "@/components/config/SlabsPanel";
import {
  type PFConfig, type ESICConfig,
  type TenantStatutoryConfig, type StatutoryConfigResponse,
  defaultPFConfig, defaultESICConfig,
  getStatutoryConfig, saveStatutoryConfig, resetStatutoryConfig, statutoryVersionsApi,
} from "@/lib/statutory-config";
import { MonthSelect } from "@/components/ui/month-select";

// ─── small helpers ────────────────────────────────────────────────────────────

const pct = (v: string) => `${(parseFloat(v) * 100).toFixed(4).replace(/\.?0+$/, "")}%`;

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

// ─── PF and ESIC ──────────────────────────────────────────────────────────────

function ComponentsNote({ what }: { what: string }) {
  return (
    <p className="text-xs text-ink-500">
      Which salary components count toward the {what} wage is set on each component —{" "}
      <Link href="/config/components" className="font-medium text-brand-700 underline-offset-2 hover:underline">Salary components</Link>.
    </p>
  );
}

function PFPanel({ cfg, onChange }: { cfg: PFConfig; onChange: (c: PFConfig) => void }) {
  const setFormula = (v: string) => {
    const { employee_formula: _drop, ...rest } = cfg;
    onChange(v ? { ...rest, employee_formula: v } : rest);
  };
  return (
    <div className="space-y-5">
      <EmployeeFormula kind="PF" value={cfg.employee_formula ?? ""} onChange={setFormula} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Employee contribution rate" help={pct(cfg.rates.employee_rate)}>
          <NumberInput value={cfg.rates.employee_rate} onChange={(v) => onChange({ ...cfg, rates: { ...cfg.rates, employee_rate: v } })} />
        </Field>
        <Field label="PF wage ceiling (₹)" help="The statutory ceiling is applied by date: ₹15,000 to 16 Sep 2026, ₹25,000 from 17 Sep 2026 (September day-weighted). Enter a higher figure only if your company uses one.">
          <NumberInput value={cfg.wage.wage_ceiling} onChange={(v) => onChange({ ...cfg, wage: { ...cfg.wage, wage_ceiling: v } })} step="500" min="0" max="999999" />
        </Field>
      </div>
      <div className="flex flex-col items-start gap-3">
      <Toggle
        checked={cfg.wage.restrict_to_ceiling}
        onChange={(v) => onChange({ ...cfg, wage: { ...cfg.wage, restrict_to_ceiling: v } })}
        label="Limit PF wage to the ceiling"
      />
      <Toggle
        checked={!!cfg.pf_on_code_wages}
        onChange={(v) => {
          const { pf_on_code_wages: _drop, ...rest } = cfg;
          onChange(v ? { ...rest, pf_on_code_wages: true } : rest);
        }}
        label="PF on the Labour Code wage (Basic + DA + allowances above half of pay), prorated for paid days"
      />
      </div>
      <ComponentsNote what="PF" />
    </div>
  );
}

function ESICPanel({ cfg, onChange }: { cfg: ESICConfig; onChange: (c: ESICConfig) => void }) {
  const setFormula = (v: string) => {
    const { employee_formula: _drop, ...rest } = cfg;
    onChange(v ? { ...rest, employee_formula: v } : rest);
  };
  return (
    <div className="space-y-5">
      <EmployeeFormula kind="ESIC" value={cfg.employee_formula ?? ""} onChange={setFormula} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Employee contribution rate" help={pct(cfg.rates.employee_rate)}>
          <NumberInput value={cfg.rates.employee_rate} onChange={(v) => onChange({ ...cfg, rates: { ...cfg.rates, employee_rate: v } })} />
        </Field>
        <Field label="ESIC wage ceiling (₹)" help="Employees above this are not covered.">
          <NumberInput value={cfg.wage.wage_ceiling} onChange={(v) => onChange({ ...cfg, wage: { ...cfg.wage, wage_ceiling: v } })} step="500" min="0" max="999999" />
        </Field>
      </div>
      <div>
        <p className="mb-2 text-[13px] font-medium text-ink-800">Rounding</p>
        <div className="flex items-center gap-4">
          {(["up", "down", "nearest"] as const).map((m) => (
            <label key={m} className="flex cursor-pointer items-center gap-2 text-sm text-ink-700">
              <input
                type="radio"
                name="esic_round"
                value={m}
                checked={cfg.rounding.mode === m}
                onChange={() => onChange({ ...cfg, rounding: { ...cfg.rounding, mode: m } })}
                className="accent-brand-600"
              />
              {m.charAt(0).toUpperCase() + m.slice(1)}
            </label>
          ))}
        </div>
      </div>
      <div className="flex flex-col gap-2">
        <Toggle
          checked={cfg.eligibility.full_month_on_entry}
          onChange={(v) => onChange({ ...cfg, eligibility: { ...cfg.eligibility, full_month_on_entry: v } })}
          label="Full-month ESIC in the joining month"
        />
        <Toggle
          checked={cfg.eligibility.continue_month_on_exit}
          onChange={(v) => onChange({ ...cfg, eligibility: { ...cfg.eligibility, continue_month_on_exit: v } })}
          label="Continue ESIC in the exit month"
        />
      </div>
      <ComponentsNote what="ESIC" />
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

const TABS = [
  { id: "pf", label: "Provident Fund" },
  { id: "esic", label: "ESIC" },
  { id: "pt", label: "Professional tax" },
  { id: "lwf", label: "Labour welfare fund" },
  { id: "minwage", label: "Minimum wages" },
];

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
  const [tab, setTab] = useState<string>("pf");
  const [confirmReset, setConfirmReset] = useState(false);

  useEffect(() => {
    const wanted = new URLSearchParams(window.location.search).get("tab");
    if (wanted && TABS.some((t) => t.id === wanted)) setTab(wanted);
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

  const chooseTab = (id: string) => {
    setTab(id);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", id);
    window.history.replaceState(null, "", url);
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
        title="Statutory engine"
        description="How PF, ESIC, professional tax, labour welfare fund and minimum wages are worked out for this company."
        meta={updatedAt ? <span>Last saved {dateTime(updatedAt)} · <Link href="/audit" className="underline-offset-2 hover:underline">change history in the audit trail</Link></span> : null}
        actions={canWrite ? (
          <Button variant="destructive-outline" type="button" onClick={() => setConfirmReset(true)} disabled={saving}>
            <RefreshCw size={14} strokeWidth={2} /> Reset to shipped defaults
          </Button>
        ) : null}
      />

      <Tabs label="Statutory settings" value={tab} onChange={chooseTab} items={TABS} />

      {error ? <AlertBanner variant="error" title="Not saved">{error}</AlertBanner> : null}

      {tab === "pf" || tab === "esic" ? (
        <>
          {inForce?.version ? (
            <AlertBanner variant="warning" title={`This month uses change ${inForce.version}, not the configuration below`}>
              Change {inForce.version} has been in force since {periodLabel(inForce.effective_from!)}. The configuration below applies to months before any dated change; editing it does not alter a month a change covers. See Dated changes at the foot of the page.
            </AlertBanner>
          ) : null}
          {!canWrite ? <AlertBanner variant="info">Your role can read this configuration but not change it.</AlertBanner> : null}

          <fieldset disabled={!canWrite} className="rounded-xl border border-ink-200 bg-white p-5 shadow-soft">
            {tab === "pf" ? (
              <PFPanel cfg={cfg.pf} onChange={(pf) => setCfg((c) => ({ ...c, pf }))} />
            ) : (
              <ESICPanel cfg={cfg.esic} onChange={(esic) => setCfg((c) => ({ ...c, esic }))} />
            )}
          </fieldset>
          <p className="text-xs text-ink-500">
            <b>Save changes</b> applies from the next validation run to every month no dated change covers;{" "}
            <b>Schedule from a month…</b> keeps it as a draft for a manager to publish. Runs already made keep the
            configuration they were validated with, and every change is in the audit trail.
          </p>
          <DatedChanges />
        </>
      ) : null}

      {tab === "pt" ? <SlabsPanel ruleType="PT" /> : null}
      {tab === "lwf" ? <SlabsPanel ruleType="LWF" /> : null}
      {tab === "minwage" ? <MinimumWagePanel /> : null}

      {tab === "pf" || tab === "esic" || changes.length > 0 ? <SaveBar
        changes={changes}
        saving={saving}
        onSave={() => void handleSave()}
        onDiscard={() => setCfg(baseline)}
        note="saving applies them to every month without a dated change"
        canSave={canWrite}
        secondary={canWrite ? <Button variant="outline" disabled={saving} onClick={() => setScheduling(true)}>Schedule from a month…</Button> : null}
      /> : null}

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
            <MonthSelect className="mt-1 block" value={fromMonth} onChange={setFromMonth} />
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
