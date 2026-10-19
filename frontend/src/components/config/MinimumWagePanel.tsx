"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Copy, Eye, Plus, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/drawer";
import { apiFetch, parseEnvelopeResponse } from "@/lib/api";
import { getReferenceStates } from "@/lib/rule-engine";
import { cn } from "@/lib/utils";

type Decision = {
  status: "not_set" | "applicable" | "not_applicable";
  applicable: boolean | null;
  effective_from: string | null;
  reason?: string | null;
  source_reference?: string | null;
};
type Rate = {
  id: string; state: string; zone: string; scheduled_employment: string; skill_category: string;
  basic_per_month: string; vda_per_month: string; working_days_basis: string;
  effective_from: string; effective_to: string | null; source_reference: string | null;
};
type Coverage = { covered: unknown[]; missing: unknown[]; employees_without_classification: number };

type Schedule = {
  key: string; state: string; zone: string; scheduled_employment: string; working_days_basis: string;
  effective_from: string; effective_to: string | null; source_reference: string; rows: Rate[];
};
type Line = { skill_category: string; basic_per_month: string; vda_per_month: string };
type General = {
  state: string; zone: string; scheduled_employment: string; working_days_basis: string;
  effective_from: string; effective_to: string; source_reference: string;
};

const SKILLS = ["unskilled", "semi-skilled", "skilled", "highly-skilled"];
const EMPTY_GENERAL: General = {
  state: "", zone: "*", scheduled_employment: "*", working_days_basis: "26",
  effective_from: "", effective_to: "", source_reference: "",
};
const today = () => new Date().toISOString().slice(0, 10);
const money = (v: string) => Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 });
const label = (s: string) => (s === "*" ? "All" : s);

function group(rates: Rate[]): Schedule[] {
  const map = new Map<string, Schedule>();
  for (const r of rates) {
    const key = [r.state, r.zone, r.scheduled_employment, r.effective_from, r.effective_to ?? "", r.working_days_basis, r.source_reference ?? ""].join("|");
    const entry = map.get(key) ?? {
      key, state: r.state, zone: r.zone, scheduled_employment: r.scheduled_employment,
      working_days_basis: r.working_days_basis, effective_from: r.effective_from,
      effective_to: r.effective_to, source_reference: r.source_reference ?? "", rows: [],
    };
    entry.rows.push(r);
    map.set(key, entry);
  }
  return [...map.values()].sort((a, b) => a.state.localeCompare(b.state) || b.effective_from.localeCompare(a.effective_from));
}

function statusOf(s: Schedule): "Active" | "Upcoming" | "Expired" {
  const now = today();
  if (s.effective_from > now) return "Upcoming";
  if (s.effective_to && s.effective_to < now) return "Expired";
  return "Active";
}

const input = "mt-1 h-9 w-full rounded-lg border border-ink-200 bg-white px-3 text-[13px] font-normal focus:outline-none focus:ring-2 focus:ring-brand-500/20";

export function MinimumWagePanel() {
  const [current, setCurrent] = useState<Decision | null>(null);
  const [history, setHistory] = useState<Decision[]>([]);
  const [rates, setRates] = useState<Rate[]>([]);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [states, setStates] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);

  // the schedule drawer
  const [drawer, setDrawer] = useState<null | { replaces: string[]; title: string }>(null);
  const [step, setStep] = useState<1 | 2>(1);
  const [general, setGeneral] = useState<General>(EMPTY_GENERAL);
  const [lines, setLines] = useState<Line[]>([{ skill_category: "", basic_per_month: "", vda_per_month: "0" }]);
  const [formError, setFormError] = useState<string | null>(null);

  // the decision drawer
  const [deciding, setDeciding] = useState(false);
  const [choice, setChoice] = useState<"yes" | "no" | "">("");
  const [effectiveFrom, setEffectiveFrom] = useState(today);
  const [reason, setReason] = useState("");
  const [reference, setReference] = useState("");

  const refresh = useCallback(async () => {
    const [decisionRes, ratesRes, coverageRes] = await Promise.all([
      apiFetch("/api/minimum-wage/applicability"), apiFetch("/api/minimum-wage/rates"), apiFetch("/api/minimum-wage/coverage"),
    ]);
    const decisions = await parseEnvelopeResponse<{ current: Decision; history: Decision[] }>(decisionRes);
    setCurrent(decisions.current);
    setHistory(decisions.history);
    setRates(await parseEnvelopeResponse<Rate[]>(ratesRes));
    setCoverage(await parseEnvelopeResponse<Coverage>(coverageRes));
  }, []);

  useEffect(() => {
    void refresh().catch((err) => toast.error(String(err)));
    getReferenceStates().then((r) => setStates(r.all_states)).catch(() => setStates([]));
  }, [refresh]);

  const schedules = useMemo(() => group(rates), [rates]);
  const shown = schedules.filter((s) => `${s.state} ${s.zone} ${s.scheduled_employment}`.toLowerCase().includes(query.trim().toLowerCase()));

  const openSchedule = (s: Schedule | null, mode: "new" | "edit" | "copy") => {
    setFormError(null);
    setStep(1);
    if (!s) {
      setGeneral({ ...EMPTY_GENERAL, effective_from: today() });
      setLines([{ skill_category: "", basic_per_month: "", vda_per_month: "0" }]);
      setDrawer({ replaces: [], title: "Create minimum wage" });
      return;
    }
    setGeneral({
      state: s.state, zone: s.zone, scheduled_employment: s.scheduled_employment, working_days_basis: String(Number(s.working_days_basis)),
      effective_from: mode === "copy" ? "" : s.effective_from, effective_to: mode === "copy" ? "" : s.effective_to ?? "",
      source_reference: mode === "copy" ? "" : s.source_reference,
    });
    setLines(s.rows.map((r) => ({ skill_category: r.skill_category, basic_per_month: String(Number(r.basic_per_month)), vda_per_month: String(Number(r.vda_per_month)) })));
    setDrawer(mode === "edit"
      ? { replaces: s.rows.map((r) => r.id), title: `Minimum wage — ${s.state}` }
      : { replaces: [], title: `Copy of ${s.state}` });
  };

  const next = () => {
    if (!general.state || !general.effective_from) {
      setFormError("Choose the state and the date it takes effect from.");
      return;
    }
    if (general.effective_to && general.effective_to < general.effective_from) {
      setFormError("The end date is before the start date.");
      return;
    }
    setFormError(null);
    setStep(2);
  };

  const saveSchedule = async () => {
    const used = lines.filter((l) => l.skill_category || l.basic_per_month);
    if (!used.length || used.some((l) => !l.skill_category || l.basic_per_month === "")) {
      setFormError("Each line needs a skill category and a basic amount.");
      return;
    }
    if (new Set(used.map((l) => l.skill_category)).size !== used.length) {
      setFormError("A skill category can appear once in a schedule.");
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      const response = await apiFetch("/api/minimum-wage/rates/schedule", {
        method: "POST",
        body: JSON.stringify({
          replaces: drawer?.replaces ?? [],
          rates: used.map((l) => ({
            state: general.state, zone: general.zone.trim() || "*", scheduled_employment: general.scheduled_employment.trim() || "*",
            skill_category: l.skill_category, basic_per_month: l.basic_per_month, vda_per_month: l.vda_per_month || "0",
            working_days_basis: general.working_days_basis || "26", effective_from: general.effective_from,
            effective_to: general.effective_to || null, source_reference: general.source_reference.trim() || null,
          })),
        }),
      });
      await parseEnvelopeResponse(response);
      await refresh();
      setDrawer(null);
      toast.success("Minimum wage saved");
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (s: Schedule) => {
    if (!confirm(`Delete the ${s.state} schedule from ${s.effective_from}?`)) return;
    try {
      for (const r of s.rows) await parseEnvelopeResponse(await apiFetch(`/api/minimum-wage/rates/${r.id}`, { method: "DELETE" }));
      await refresh();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not delete.");
    }
  };

  const saveDecision = async () => {
    if (!choice || !effectiveFrom || (choice === "no" && !reason.trim())) {
      toast.error("Choose Yes or No, an effective date, and a reason when selecting No.");
      return;
    }
    setBusy(true);
    try {
      await parseEnvelopeResponse(await apiFetch("/api/minimum-wage/applicability", {
        method: "POST",
        body: JSON.stringify({ applicable: choice === "yes", effective_from: effectiveFrom, reason: reason.trim() || null, source_reference: reference.trim() || null }),
      }));
      await refresh();
      setDeciding(false);
      toast.success("Decision saved");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Could not save decision.");
    } finally {
      setBusy(false);
    }
  };

  const decisionText = current?.status === "applicable" ? "Applies" : current?.status === "not_applicable" ? "Does not apply" : "Not decided";

  return (
    <div className="space-y-4">
      <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-ink-200 bg-white px-4 py-3 shadow-soft">
        <div className="text-[13px]">
          <span className="font-semibold text-ink-900">Minimum wage check: </span>
          <span className={cn("font-medium", current?.status === "not_set" ? "text-warning-800" : "text-ink-800")}>{decisionText}</span>
          {current?.effective_from ? <span className="text-ink-500"> · from {current.effective_from}</span> : null}
          {current?.status === "not_set" ? <span className="text-warning-800"> — the check will not run until this is decided.</span> : null}
        </div>
        <Button type="button" variant="outline" onClick={() => { setChoice(current?.applicable == null ? "" : current.applicable ? "yes" : "no"); setReason(""); setReference(""); setEffectiveFrom(today()); setDeciding(true); }}>
          {current?.status === "not_set" ? "Decide" : "Change decision"}
        </Button>
      </section>

      {current?.applicable ? (
        <section className="rounded-xl border border-ink-200 bg-white shadow-soft">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-100 p-3">
            <label className="relative block w-full max-w-xs">
              <Search size={14} aria-hidden className="pointer-events-none absolute left-2.5 top-2.5 text-ink-400" />
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by state" aria-label="Search schedules"
                className="h-9 w-full rounded-lg border border-ink-200 pl-8 pr-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-brand-500/20" />
            </label>
            <Button type="button" onClick={() => openSchedule(null, "new")}><Plus size={14} /> Create new minimum wage</Button>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-[13px]">
              <thead>
                <tr className="bg-ink-50/80 text-[11px] font-semibold text-ink-500">
                  <th className="px-4 py-2.5">Location</th><th className="px-4 py-2.5">Scheduled employment · zone</th>
                  <th className="px-4 py-2.5">Skill categories</th><th className="px-4 py-2.5">Effective</th>
                  <th className="px-4 py-2.5">Status</th><th className="px-4 py-2.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {shown.length === 0 ? (
                  <tr><td colSpan={6} className="px-4 py-10 text-center text-ink-500">{schedules.length ? "No schedule matches the search." : "No minimum wage schedules yet. Choose Create new minimum wage."}</td></tr>
                ) : shown.map((s) => {
                  const status = statusOf(s);
                  return (
                    <tr key={s.key} className="hover:bg-ink-50/60">
                      <td className="px-4 py-3 font-medium text-ink-900">{s.state}</td>
                      <td className="px-4 py-3 text-ink-700">{label(s.scheduled_employment)} · {label(s.zone)}</td>
                      <td className="px-4 py-3 text-ink-700">{s.rows.map((r) => `${r.skill_category} ₹${money(r.basic_per_month)}`).join(", ")}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-ink-700">{s.effective_from}{s.effective_to ? ` → ${s.effective_to}` : " →"}</td>
                      <td className="px-4 py-3">
                        <span className={cn("rounded px-1.5 py-0.5 text-[11px] font-medium",
                          status === "Active" ? "bg-success-50 text-success-700" : status === "Upcoming" ? "bg-brand-50 text-brand-800" : "bg-ink-100 text-ink-600")}>{status}</span>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-right">
                        <button type="button" onClick={() => openSchedule(s, "copy")} className="mr-1 inline-flex items-center gap-1 rounded-md border border-ink-200 px-2 py-1 text-xs font-medium text-ink-700 hover:bg-ink-50"><Copy size={12} /> Copy</button>
                        <button type="button" onClick={() => openSchedule(s, "edit")} className="mr-1 inline-flex items-center gap-1 rounded-md border border-ink-200 px-2 py-1 text-xs font-medium text-ink-700 hover:bg-ink-50"><Eye size={12} /> View</button>
                        <button type="button" onClick={() => void remove(s)} aria-label={`Delete ${s.state} schedule`} className="inline-flex items-center rounded-md px-1.5 py-1 text-danger-600 hover:bg-danger-50"><Trash2 size={13} /></button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {coverage ? (
            <p className="border-t border-ink-100 px-4 py-2.5 text-xs text-ink-500">
              Workforce coverage: {coverage.covered.length} state and skill pairs covered, {coverage.missing.length} missing;{" "}
              {coverage.employees_without_classification} employees have no state or skill category.
            </p>
          ) : null}
        </section>
      ) : null}

      <Drawer
        open={!!drawer}
        onClose={() => setDrawer(null)}
        width="lg"
        title={drawer?.title ?? ""}
        description={
          <span className="flex items-center gap-3 text-xs">
            <span className={cn("flex items-center gap-1.5", step === 1 ? "font-semibold text-ink-900" : "text-ink-500")}>
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-ink-800 text-[11px] text-white">1</span> General
            </span>
            <span className="h-px w-8 bg-ink-200" />
            <span className={cn("flex items-center gap-1.5", step === 2 ? "font-semibold text-ink-900" : "text-ink-500")}>
              <span className={cn("flex h-5 w-5 items-center justify-center rounded-full text-[11px] text-white", step === 2 ? "bg-ink-800" : "bg-ink-300")}>2</span> Configure
            </span>
          </span>
        }
        footer={
          <div className="flex w-full items-center justify-between gap-2">
            <p className="text-xs text-danger-700" role="alert">{formError}</p>
            <div className="flex gap-2">
              <Button type="button" variant="outline" onClick={() => setDrawer(null)}>Cancel</Button>
              {step === 2 ? <Button type="button" variant="outline" onClick={() => setStep(1)}>Previous</Button> : null}
              {step === 1 ? <Button type="button" onClick={next}>Next</Button> : <Button type="button" disabled={busy} onClick={() => void saveSchedule()}>{busy ? "Saving…" : "Save"}</Button>}
            </div>
          </div>
        }
      >
        {step === 1 ? (
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-[13px] font-medium text-ink-800">State *
              <select className={input} value={general.state} onChange={(e) => setGeneral({ ...general, state: e.target.value })}>
                <option value="">Select option</option>
                {states.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
            <label className="block text-[13px] font-medium text-ink-800">Scheduled employment
              <input className={input} value={general.scheduled_employment} onChange={(e) => setGeneral({ ...general, scheduled_employment: e.target.value })} placeholder="* means all" />
            </label>
            <label className="block text-[13px] font-medium text-ink-800">Zone or area
              <input className={input} value={general.zone} onChange={(e) => setGeneral({ ...general, zone: e.target.value })} placeholder="* means all" />
            </label>
            <label className="block text-[13px] font-medium text-ink-800">Working days in a month
              <input className={input} type="number" min={1} max={31} value={general.working_days_basis} onChange={(e) => setGeneral({ ...general, working_days_basis: e.target.value })} />
            </label>
            <label className="block text-[13px] font-medium text-ink-800">Effective from *
              <input className={input} type="date" value={general.effective_from} onChange={(e) => setGeneral({ ...general, effective_from: e.target.value })} />
            </label>
            <label className="block text-[13px] font-medium text-ink-800">Effective to
              <input className={input} type="date" value={general.effective_to} onChange={(e) => setGeneral({ ...general, effective_to: e.target.value })} />
            </label>
            <label className="block text-[13px] font-medium text-ink-800 sm:col-span-2">Official notification or URL
              <input className={input} value={general.source_reference} maxLength={512} onChange={(e) => setGeneral({ ...general, source_reference: e.target.value })} placeholder="Where these rates come from" />
            </label>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-[15px] font-semibold text-ink-900">Rates by skill category</h3>
              <Button type="button" variant="outline" onClick={() => setLines([...lines, { skill_category: "", basic_per_month: "", vda_per_month: "0" }])}><Plus size={14} /> Add record</Button>
            </div>
            <table className="w-full text-left text-[13px]">
              <thead><tr className="text-[11px] font-semibold text-ink-500"><th className="pb-1.5">Skill category</th><th className="pb-1.5">Basic per month (₹)</th><th className="pb-1.5">VDA per month (₹)</th><th /></tr></thead>
              <tbody>
                {lines.map((l, i) => (
                  <tr key={i}>
                    <td className="pr-2 pb-2">
                      <select className={input.replace("mt-1 ", "")} value={l.skill_category} onChange={(e) => setLines(lines.map((x, j) => j === i ? { ...x, skill_category: e.target.value } : x))}>
                        <option value="">Select option</option>
                        {SKILLS.map((s) => <option key={s} value={s}>{s}</option>)}
                      </select>
                    </td>
                    <td className="pr-2 pb-2"><input className={input.replace("mt-1 ", "")} type="number" min={0} value={l.basic_per_month} onChange={(e) => setLines(lines.map((x, j) => j === i ? { ...x, basic_per_month: e.target.value } : x))} /></td>
                    <td className="pr-2 pb-2"><input className={input.replace("mt-1 ", "")} type="number" min={0} value={l.vda_per_month} onChange={(e) => setLines(lines.map((x, j) => j === i ? { ...x, vda_per_month: e.target.value } : x))} /></td>
                    <td className="pb-2 text-right"><button type="button" aria-label="Delete line" disabled={lines.length === 1} onClick={() => setLines(lines.filter((_, j) => j !== i))} className="rounded-md p-1.5 text-danger-600 hover:bg-danger-50 disabled:opacity-30"><Trash2 size={14} /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs text-ink-500">Validation compares an employee&apos;s basic and VDA with the line for their state and skill category.</p>
          </div>
        )}
      </Drawer>

      <Drawer
        open={deciding}
        onClose={() => setDeciding(false)}
        title="Does the minimum wage check apply?"
        description="A missing decision stops the check; it never assumes Yes or No."
        footer={<div className="flex w-full justify-end gap-2"><Button type="button" variant="outline" onClick={() => setDeciding(false)}>Cancel</Button><Button type="button" disabled={busy} onClick={() => void saveDecision()}>Save</Button></div>}
      >
        <div className="space-y-4">
          <p className="text-xs text-warning-800">Selecting No skips this product&apos;s comparison. It is not a legal exemption; record the reason and review it with your labour adviser.</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-[13px] font-medium text-ink-800">Applies to this company? *
              <select className={input} value={choice} onChange={(e) => setChoice(e.target.value as "yes" | "no" | "")}>
                <option value="">Select option</option><option value="yes">Yes</option><option value="no">No</option>
              </select>
            </label>
            <label className="block text-[13px] font-medium text-ink-800">Effective from *
              <input className={input} type="date" value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} />
            </label>
          </div>
          <label className="block text-[13px] font-medium text-ink-800">Reason {choice === "no" ? "(required for No)" : "(optional)"}
            <textarea className={`${input} h-auto min-h-[64px] py-2`} maxLength={1000} value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <label className="block text-[13px] font-medium text-ink-800">Notification or advice reference
            <input className={input} maxLength={512} value={reference} onChange={(e) => setReference(e.target.value)} />
          </label>
          {history.length > 0 ? (
            <div className="text-xs text-ink-600">
              <p className="mb-1 font-semibold">Earlier decisions</p>
              {history.map((h) => <p key={h.effective_from}>{h.effective_from}: {h.applicable ? "Yes" : "No"}{h.reason ? ` — ${h.reason}` : ""}</p>)}
            </div>
          ) : null}
        </div>
      </Drawer>
    </div>
  );
}
