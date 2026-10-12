"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Eraser, History, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { apiFetch, parseEnvelopeResponse } from "@/lib/api";
import { dataProtection, type ErasurePlan, type RetainedRecord } from "@/lib/data-protection";

type Context = { role: string | null };

function fetchContext() {
  return apiFetch("/api/org/context").then((r) => parseEnvelopeResponse<Context>(r));
}

function Counts({ counts, empty }: { counts: Record<string, number>; empty: string }) {
  const entries = Object.entries(counts);
  if (!entries.length) return <p className="text-xs text-ink-500">{empty}</p>;
  return (
    <ul className="grid gap-x-6 gap-y-1 text-xs text-ink-700 sm:grid-cols-2">
      {entries.map(([label, n]) => (
        <li key={label} className="flex justify-between gap-3 border-b border-ink-100 py-1">
          <span>{label}</span>
          <span className="font-mono tabular-nums text-ink-900">{n.toLocaleString("en-IN")}</span>
        </li>
      ))}
    </ul>
  );
}

function Retained({ rows }: { rows: RetainedRecord[] }) {
  if (!rows.length) return null;
  return (
    <AlertBanner variant="warning" title="Still names this person after erasure">
      <ul className="mt-1 space-y-1.5">
        {rows.map((r) => (
          <li key={r.store}>
            <strong>
              {r.store} ({r.count})
            </strong>{" "}
            — {r.why}
          </li>
        ))}
      </ul>
    </AlertBanner>
  );
}

const fmt = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "—";

export default function DataProtectionPage() {
  const qc = useQueryClient();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const context = useQuery({ queryKey: ["org-context"], queryFn: fetchContext, enabled: mounted });
  const isOwner = context.data?.role === "owner";
  const policy = useQuery({ queryKey: ["retention"], queryFn: dataProtection.policy, enabled: mounted });
  const erasures = useQuery({
    queryKey: ["erasures"],
    queryFn: dataProtection.erasures,
    enabled: mounted && !!context.data && ["owner", "manager"].includes(context.data.role ?? ""),
  });

  // Retention form
  const [months, setMonths] = useState("");
  const [why, setWhy] = useState("");
  const [preview, setPreview] = useState<{ keep_from: string; counts: Record<string, number> } | null>(null);
  useEffect(() => {
    if (policy.data?.payroll_months) setMonths(String(policy.data.payroll_months));
  }, [policy.data?.payroll_months]);

  const previewRetention = useMutation({
    mutationFn: () => dataProtection.previewRetention(Number(months)),
    onSuccess: setPreview,
    onError: (e: Error) => toast.error(e.message),
  });
  const saveRetention = useMutation({
    mutationFn: (value: number | null) => dataProtection.setRetention(value, why.trim()),
    onSuccess: () => {
      toast.success("Retention period saved");
      setWhy("");
      setPreview(null);
      void qc.invalidateQueries({ queryKey: ["retention"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const applyNow = useMutation({
    mutationFn: dataProtection.applyRetention,
    onSuccess: (r) => {
      const n = Object.values(r.counts).reduce((a, b) => a + b, 0);
      toast.success(n ? `Removed ${n.toLocaleString("en-IN")} records past the retention period` : "Nothing was older than the period");
      void qc.invalidateQueries({ queryKey: ["retention"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  // Erasure form
  const [employeeId, setEmployeeId] = useState("");
  const [confirmId, setConfirmId] = useState("");
  const [eraseWhy, setEraseWhy] = useState("");
  const [plan, setPlan] = useState<ErasurePlan | null>(null);
  const previewErase = useMutation({
    mutationFn: () => dataProtection.previewErasure(employeeId.trim()),
    onSuccess: setPlan,
    onError: (e: Error) => toast.error(e.message),
  });
  const erase = useMutation({
    mutationFn: () => dataProtection.erase(employeeId.trim(), confirmId.trim(), eraseWhy.trim()),
    onSuccess: () => {
      toast.success(`Personal data of ${employeeId.trim()} erased`);
      setEmployeeId("");
      setConfirmId("");
      setEraseWhy("");
      setPlan(null);
      void qc.invalidateQueries({ queryKey: ["erasures"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const monthsNum = Number(months);
  const min = policy.data?.min_months ?? 12;
  const max = policy.data?.max_months ?? 180;
  const monthsValid = Number.isInteger(monthsNum) && monthsNum >= min && monthsNum <= max;
  const planHasData = !!plan && Object.keys(plan.counts).length > 0;

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Configuration & admin"
        title="Data protection"
        description="How long this company's payroll data is kept here, and erasing one person's data on request. Every change is an owner's decision and is written to the audit trail."
      />

      {policy.isError && (
        <AlertBanner variant="error" title="Could not load the retention policy">
          {(policy.error as Error).message}
        </AlertBanner>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Archive size={16} className="text-brand-600" />
            <CardTitle>Retention period</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {policy.data && (
            <AlertBanner variant={policy.data.status === "set" ? "info" : "warning"}
              title={policy.data.status === "set" ? `${policy.data.payroll_months} months` : "No retention period set"}>
              {policy.data.statement}
              {policy.data.set_by && (
                <span className="block text-xs text-ink-600">
                  Set by {policy.data.set_by} on {fmt(policy.data.set_at)}. Reason: {policy.data.reason}
                </span>
              )}
              {policy.data.last_applied_at && (
                <span className="block text-xs text-ink-600">Last applied {fmt(policy.data.last_applied_at)}.</span>
              )}
            </AlertBanner>
          )}

          {policy.data?.pending && Object.keys(policy.data.pending.counts).length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-semibold text-ink-700">
                Due for removal on the next daily pass (periods before{" "}
                {new Date(policy.data.pending.keep_from).toLocaleDateString("en-IN", { month: "long", year: "numeric" })})
              </p>
              <Counts counts={policy.data.pending.counts} empty="" />
            </div>
          )}

          <p className="text-xs text-ink-500">
            Each payroll period older than the window is removed everywhere it is held — register, uploads,
            validation runs and findings, attendance, bank files, payment-file checks and the month&apos;s sign-off —
            and leavers whose exit is older leave the employee master and CTC history. The audit trail is kept.
            Statutory record-keeping is the job of your payroll system of record; this is the copy held for checking.
          </p>

          {isOwner ? (
            <div className="grid gap-3 sm:grid-cols-[10rem_minmax(0,1fr)_auto] sm:items-end">
              <label className="space-y-1 text-xs font-medium text-ink-700">
                Months to keep ({min}–{max})
                <Input type="number" min={min} max={max} value={months}
                  onChange={(e) => { setMonths(e.target.value); setPreview(null); }} />
              </label>
              <label className="space-y-1 text-xs font-medium text-ink-700">
                Reason (recorded)
                <Input value={why} onChange={(e) => setWhy(e.target.value)} placeholder="e.g. Board resolution, 3 Oct 2026" />
              </label>
              <div className="flex gap-2">
                <Button type="button" variant="outline" disabled={!monthsValid || previewRetention.isPending}
                  onClick={() => previewRetention.mutate()}>
                  Preview
                </Button>
                <Button type="button" disabled={!monthsValid || why.trim().length < 5 || !preview || saveRetention.isPending}
                  onClick={() => saveRetention.mutate(monthsNum)}>
                  Save period
                </Button>
              </div>
            </div>
          ) : (
            <p className="text-xs text-ink-500">Only an owner can change the retention period.</p>
          )}

          {preview && (
            <div className="space-y-2 rounded-lg border border-ink-200 p-3">
              <p className="text-xs font-semibold text-ink-700">
                With {monthsNum} months, periods before{" "}
                {new Date(preview.keep_from).toLocaleDateString("en-IN", { month: "long", year: "numeric" })} would be removed:
              </p>
              <Counts counts={preview.counts} empty="Nothing held is older than that today." />
            </div>
          )}

          {isOwner && policy.data?.status === "set" && (
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" disabled={applyNow.isPending} onClick={() => applyNow.mutate()}>
                Apply now
              </Button>
              <Button type="button" variant="ghost" disabled={why.trim().length < 5 || saveRetention.isPending}
                onClick={() => saveRetention.mutate(null)} title="Stop deleting; keep everything from now on">
                Remove the period
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Eraser size={16} className="text-brand-600" />
            <CardTitle>Erase one person&apos;s data</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-xs text-ink-500">
            For a request from an employee or former employee, made through your company. Their master, CTC and
            attendance records are deleted. In months you keep, their pay stays so the month still adds up, but the
            person is replaced by an anonymous token and every identifier — name, PAN, Aadhaar, UAN, ESI and PF
            numbers, bank account, date of birth, contact details — is removed. This cannot be undone.
          </p>
          {isOwner ? (
            <>
              <div className="grid gap-3 sm:grid-cols-[12rem_auto] sm:items-end">
                <label className="space-y-1 text-xs font-medium text-ink-700">
                  Employee ID
                  <Input value={employeeId} className="font-mono"
                    onChange={(e) => { setEmployeeId(e.target.value); setPlan(null); }} />
                </label>
                <div>
                  <Button type="button" variant="outline" disabled={!employeeId.trim() || previewErase.isPending}
                    onClick={() => previewErase.mutate()}>
                    Find their data
                  </Button>
                </div>
              </div>

              {plan && !planHasData && (
                <AlertBanner variant="info" title={`No data held for ${plan.employee_id}`}>
                  Check the ID exactly as it appears in the register.
                </AlertBanner>
              )}

              {plan && planHasData && (
                <div className="space-y-3 rounded-lg border border-ink-200 p-3">
                  <p className="text-xs font-semibold text-ink-700">What erasing {plan.employee_id} changes</p>
                  <Counts counts={plan.counts} empty="" />
                  <Retained rows={plan.retained} />
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="space-y-1 text-xs font-medium text-ink-700">
                      Type the employee ID again to confirm
                      <Input value={confirmId} className="font-mono" onChange={(e) => setConfirmId(e.target.value)} />
                    </label>
                    <label className="space-y-1 text-xs font-medium text-ink-700">
                      Reason and request reference (recorded)
                      <Input value={eraseWhy} onChange={(e) => setEraseWhy(e.target.value)}
                        placeholder="e.g. Data principal request DP-2026-014" />
                    </label>
                  </div>
                  <Button type="button" variant="destructive"
                    disabled={confirmId.trim() !== plan.employee_id || eraseWhy.trim().length < 5 || erase.isPending}
                    onClick={() => erase.mutate()}>
                    Erase permanently
                  </Button>
                </div>
              )}
            </>
          ) : (
            <p className="text-xs text-ink-500">Only an owner can erase data.</p>
          )}
        </CardContent>
      </Card>

      {erasures.data && (
        <Card className="overflow-hidden">
          <div className="flex items-center gap-2 border-b border-ink-100 px-5 py-4 text-sm font-semibold text-ink-800">
            <History size={16} className="text-ink-500" />
            Erasures carried out
          </div>
          {!erasures.data.length ? (
            <EmptyState icon={ShieldCheck} title="No erasures yet" description="Each erasure is listed here with what it changed and what it kept." />
          ) : (
            <ul className="divide-y divide-ink-100">
              {erasures.data.map((r) => (
                <li key={r.id} className="space-y-2 px-5 py-3 text-sm">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="font-mono font-semibold text-ink-900">{r.employee_id}</span>
                    <span className="text-xs text-ink-500">
                      {fmt(r.completed_at)} · {r.requested_by}
                    </span>
                  </div>
                  <p className="text-xs text-ink-600">{r.reason}</p>
                  <Counts counts={r.counts} empty="" />
                  <Retained rows={r.retained} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </div>
  );
}
