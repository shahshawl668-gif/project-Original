"use client";

import { useEffect, useState } from "react";
import { apiFetch, parseEnvelopeResponse } from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";

type Decision = {
  status: "not_set" | "applicable" | "not_applicable";
  applicable: boolean | null;
  effective_from: string | null;
  reason?: string | null;
  source_reference?: string | null;
};
type Rate = {
  id: string; state: string; zone: string; scheduled_employment: string;
  skill_category: string; basic_per_month: string; vda_per_month: string;
  effective_from: string; effective_to: string | null; source_reference: string | null;
};
type Coverage = {
  covered: { state: string; skill_category: string }[];
  missing: { state: string; skill_category: string }[];
  employees_without_classification: number;
};

const today = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
};

export default function MinimumWageSettings() {
  const [current, setCurrent] = useState<Decision | null>(null);
  const [history, setHistory] = useState<Decision[]>([]);
  const [rates, setRates] = useState<Rate[]>([]);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [choice, setChoice] = useState<"yes" | "no" | "">("");
  const [effectiveFrom, setEffectiveFrom] = useState(today);
  const [reason, setReason] = useState("");
  const [reference, setReference] = useState("");
  const [busy, setBusy] = useState(false);
  const [rate, setRate] = useState({
    state: "", zone: "*", scheduled_employment: "", skill_category: "",
    basic_per_month: "", vda_per_month: "0", effective_from: today(),
    source_reference: "",
  });

  const refresh = async () => {
    const [decisionRes, ratesRes, coverageRes] = await Promise.all([
      apiFetch("/api/minimum-wage/applicability"),
      apiFetch("/api/minimum-wage/rates"),
      apiFetch("/api/minimum-wage/coverage"),
    ]);
    const decisions = await parseEnvelopeResponse<{ current: Decision; history: Decision[] }>(decisionRes);
    setCurrent(decisions.current);
    setHistory(decisions.history);
    setRates(await parseEnvelopeResponse<Rate[]>(ratesRes));
    setCoverage(await parseEnvelopeResponse<Coverage>(coverageRes));
  };

  useEffect(() => { void refresh().catch((err) => toast.error(String(err))); }, []);

  const saveDecision = async () => {
    if (!choice || !effectiveFrom || (choice === "no" && !reason.trim())) {
      toast.error("Choose Yes or No, an effective date, and a reason when selecting No.");
      return;
    }
    setBusy(true);
    try {
      const response = await apiFetch("/api/minimum-wage/applicability", {
        method: "POST",
        body: JSON.stringify({
          applicable: choice === "yes", effective_from: effectiveFrom,
          reason: reason.trim() || null, source_reference: reference.trim() || null,
        }),
      });
      await parseEnvelopeResponse(response);
      await refresh();
      toast.success("Applicability saved");
    } catch (err) { toast.error(err instanceof Error ? err.message : "Could not save decision."); }
    finally { setBusy(false); }
  };

  const addRate = async () => {
    if (!rate.state.trim() || !rate.scheduled_employment.trim() || !rate.skill_category ||
        !rate.effective_from || !rate.source_reference.trim()) {
      toast.error("Add state, scheduled employment, skill, effective date and notification source.");
      return;
    }
    setBusy(true);
    try {
      const response = await apiFetch("/api/minimum-wage/rates", {
        method: "POST", body: JSON.stringify({
          ...rate, basic_per_month: rate.basic_per_month || "0", vda_per_month: rate.vda_per_month || "0",
        }),
      });
      await parseEnvelopeResponse(response);
      await refresh();
      toast.success("Rate added");
    } catch (err) { toast.error(err instanceof Error ? err.message : "Could not add rate."); }
    finally { setBusy(false); }
  };

  return <div className="mx-auto max-w-5xl space-y-6">
    <PageHeader eyebrow="Statutory settings" title="Minimum wage"
      description="Record whether the check applies to this company, then maintain the applicable notified rates." />

    <section className="space-y-4 rounded-2xl border bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">Required applicability decision</h2>
      <p className="text-sm text-slate-600">Current: <strong>{current?.status === "applicable" ? "Yes" : current?.status === "not_applicable" ? "No" : "Not selected"}</strong>
        {current?.effective_from ? ` (effective ${current.effective_from})` : ""}. A missing decision blocks the minimum-wage check; it does not silently assume Yes or No.</p>
      <p className="text-xs text-amber-800">Selecting No skips this product&apos;s minimum-wage comparison. It is not a legal exemption decision; record the reason and review applicability with the client&apos;s labour adviser.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm font-medium">Does the minimum-wage check apply to this entity?
          <select className="mt-1 w-full rounded-lg border p-2" value={choice} onChange={(e) => setChoice(e.target.value as "yes" | "no" | "")}>
            <option value="">Select Yes or No</option><option value="yes">Yes</option><option value="no">No</option>
          </select>
        </label>
        <label className="text-sm font-medium">Effective from
          <input type="date" className="mt-1 w-full rounded-lg border p-2" value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} />
        </label>
      </div>
      <label className="block text-sm font-medium">Reason {choice === "no" ? "(required for No)" : "(optional)"}
        <textarea className="mt-1 w-full rounded-lg border p-2" maxLength={1000} value={reason}
          onChange={(e) => setReason(e.target.value)} placeholder="Record why this company is or is not covered." />
      </label>
      <label className="block text-sm font-medium">Notification or advice reference (optional)
        <input className="mt-1 w-full rounded-lg border p-2" maxLength={512} value={reference} onChange={(e) => setReference(e.target.value)} />
      </label>
      <Button onClick={() => void saveDecision()} disabled={busy}>Save decision</Button>
      {history.length > 0 && <div className="text-sm text-slate-600">
        <h3 className="font-semibold">Decision history</h3>
        {history.map((item) => <p key={item.effective_from}>{item.effective_from}: {item.applicable ? "Yes" : "No"}{item.reason ? ` — ${item.reason}` : ""}</p>)}
      </div>}
    </section>

    {current?.applicable && <>
      <section className="space-y-4 rounded-2xl border bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold">Applicable rate schedule</h2>
        <p className="text-sm text-slate-600">Add rates from the applicable official notification. State alone is insufficient: select the scheduled employment, zone and skill category. Rates are effective dated.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          {([
            ["state", "State"], ["scheduled_employment", "Scheduled employment"],
            ["zone", "Zone or area"], ["skill_category", "Skill category"],
            ["basic_per_month", "Basic per month (₹)"], ["vda_per_month", "VDA per month (₹)"],
            ["effective_from", "Effective from"], ["source_reference", "Official notification / URL"],
          ] as const).map(([key, label]) => <label key={key} className="text-sm font-medium">{label}
            {key === "skill_category" ? <select className="mt-1 w-full rounded-lg border p-2" value={rate.skill_category}
              onChange={(e) => setRate({ ...rate, skill_category: e.target.value })}>
              <option value="">Select skill</option>
              {["unskilled", "semi-skilled", "skilled", "highly-skilled"].map((skill) => <option key={skill} value={skill}>{skill}</option>)}
            </select> : <input className="mt-1 w-full rounded-lg border p-2" type={key === "effective_from" ? "date" : "text"}
              value={rate[key]} onChange={(e) => setRate({ ...rate, [key]: e.target.value })} />}
          </label>)}
        </div>
        <Button onClick={() => void addRate()} disabled={busy}>Add notified rate</Button>
        {coverage && <p className="text-sm text-slate-600">Workforce coverage: {coverage.covered.length} state/skill pairs covered; {coverage.missing.length} missing; {coverage.employees_without_classification} employees missing state or skill classification.</p>}
        <div className="overflow-x-auto"><table className="min-w-full text-left text-sm">
          <thead><tr className="border-b text-slate-500"><th className="p-2">State</th><th className="p-2">Schedule / zone</th><th className="p-2">Skill</th><th className="p-2">Basic + VDA</th><th className="p-2">Effective</th><th className="p-2">Source</th></tr></thead>
          <tbody>{rates.map((item) => <tr key={item.id} className="border-b">
            <td className="p-2">{item.state}</td><td className="p-2">{item.scheduled_employment} / {item.zone}</td>
            <td className="p-2">{item.skill_category}</td><td className="p-2">₹{item.basic_per_month} + ₹{item.vda_per_month}</td>
            <td className="p-2">{item.effective_from}</td><td className="p-2 break-all">{item.source_reference || "Not recorded"}</td>
          </tr>)}</tbody>
        </table></div>
      </section>
    </>}
  </div>;
}
