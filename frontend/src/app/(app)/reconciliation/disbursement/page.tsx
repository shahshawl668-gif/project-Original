"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertOctagon,
  CheckCircle2,
  Download,
  FileCheck2,
  Loader2,
  PauseCircle,
  ShieldCheck,
  UploadCloud,
} from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Stat } from "@/components/ui/kpi-card";
import { Tabs } from "@/components/ui/tabs";
import { useAuth } from "@/context/AuthContext";
import { useEntity } from "@/context/EntityContext";
import {
  SEVERITY_TEXT,
  SEVERITY_TONE,
  VERDICT_TEXT,
  approveRun,
  createRun,
  downloadRun,
  fetchCatalogue,
  fetchRun,
  fetchRuns,
  fetchSettings,
  money,
  saveSettings,
  type Catalogue,
  type DownloadKind,
  type Finding,
  type RunDetail,
  type Settings,
  type Severity,
  type Slot,
  type Verdict,
} from "@/lib/disbursement";
import { saveBlob } from "@/lib/download";
import { currentPeriod } from "@/lib/reconciliation";
import { cn } from "@/lib/utils";
import { useWorkingPeriod } from "@/lib/workspace";

const WRITE_ROLES = new Set(["owner", "manager", "analyst"]);
const ADMIN_ROLES = new Set(["owner", "manager"]);

const SLOT_HINT: Record<Slot, string> = {
  bank_file: "The payment file your HRMS produced for the bank — exactly as it would be uploaded.",
  register: "This month's payroll register, with net pay and total salary payable.",
  bank_master: "Employee bank details on record: account, IFSC, name as per bank, verification.",
  change_log: "Changes to bank details, with dates and approval status.",
  previous: "Last month's payments. Leave empty to use last month's approved check here.",
  hold_list: "Employees whose salary is on hold this month.",
  offcycle: "Payments already made outside this run (advances, F&F paid separately).",
};

/**
 * Salary payment file check.
 *
 * Upload, check, read, approve — and the page never shows a green state it has
 * not earned: checks that did not run are listed with the verdict every time,
 * and a stopped file has no clean copy to download. Nothing here sends a file
 * to a bank; a person uploads the approved clean file themselves.
 */
export default function DisbursementPage() {
  const { activeRole } = useEntity();
  const [tab, setTab] = useState("check");
  const [runId, setRunId] = useState<string | null>(null);
  const canWrite = WRITE_ROLES.has(activeRole ?? "");
  const canAdmin = ADMIN_ROLES.has(activeRole ?? "");
  const catalogue = useQuery({ queryKey: ["dsb-catalogue"], queryFn: fetchCatalogue });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Payment file check"
        description="Is this salary payment file safe to release? Checked here against the register and bank master; released by a person. Nothing is sent to a bank."
      />
      <Tabs
        label="Payment file check"
        value={tab}
        onChange={setTab}
        items={[
          { id: "check", label: "Check a file" },
          { id: "history", label: "History" },
          { id: "settings", label: "Settings" },
        ]}
      />
      {tab === "check" && (
        <>
          {canWrite ? (
            <CheckForm catalogue={catalogue.data} onChecked={setRunId} />
          ) : (
            <AlertBanner variant="info" title="View only">
              Checking a payment file, and reading its findings, shows bank account numbers in full, so it needs an
              analyst, manager or owner of this company. The history tab shows each check&apos;s verdict and totals.
            </AlertBanner>
          )}
          {runId && canWrite && <RunView runId={runId} onOpen={setRunId} />}
        </>
      )}
      {tab === "history" && (
        <History
          onOpen={(id) => {
            setRunId(id);
            setTab("check");
          }}
          canOpen={canWrite}
        />
      )}
      {tab === "settings" && catalogue.data && <SettingsPanel catalogue={catalogue.data} canEdit={canAdmin} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Upload and check
// ---------------------------------------------------------------------------
function CheckForm({ catalogue, onChecked }: { catalogue?: Catalogue; onChecked: (id: string) => void }) {
  const queryClient = useQueryClient();
  const working = useWorkingPeriod();
  const period = working.period ?? currentPeriod();
  const settings = useQuery({ queryKey: ["dsb-settings"], queryFn: fetchSettings });
  const [files, setFiles] = useState<Partial<Record<Slot, File>>>({});
  const [valueDate, setValueDate] = useState("");
  const [profileKey, setProfileKey] = useState<string>("");
  const [usePrevious, setUsePrevious] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!profileKey && settings.data) setProfileKey(settings.data.profile_key);
  }, [settings.data, profileKey]);

  const run = useMutation({
    mutationFn: () => createRun({ period, valueDate, profileKey, usePreviousApproved: usePrevious, files }),
    onSuccess: (r) => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["dsb-runs"] });
      onChecked(r.id);
    },
    onError: (err: Error) => setError(err.message),
  });

  const ready = Boolean(files.bank_file && files.register && profileKey);

  return (
    <Card>
      <CardContent className="space-y-4 py-5">
        {error && (
          <AlertBanner variant="error" title="The file was not checked">
            {error}
          </AlertBanner>
        )}
        <div className="flex flex-wrap items-end gap-3">
          <label>
            <span className="mb-1.5 block text-[11px] font-semibold text-ink-500">Pay period</span>
            <input
              type="month"
              value={period}
              onChange={(e) => e.target.value && working.setPeriod(e.target.value)}
              className="h-9 rounded-lg border border-ink-200 bg-white px-3 text-sm text-ink-900"
            />
          </label>
          <label>
            <span className="mb-1.5 block text-[11px] font-semibold text-ink-500">Value date (optional)</span>
            <input
              type="date"
              value={valueDate}
              onChange={(e) => setValueDate(e.target.value)}
              className="h-9 rounded-lg border border-ink-200 bg-white px-3 text-sm text-ink-900"
            />
          </label>
          <label>
            <span className="mb-1.5 block text-[11px] font-semibold text-ink-500">Column layout</span>
            <select
              value={profileKey}
              onChange={(e) => setProfileKey(e.target.value)}
              className="h-9 rounded-lg border border-ink-200 bg-white px-3 text-sm text-ink-900"
            >
              {(catalogue?.profiles ?? []).map((p) => (
                <option key={p.key} value={p.key}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          {(catalogue?.inputs ?? []).map((input) => (
            <label
              key={input.slot}
              className={cn(
                "flex min-w-0 flex-col gap-1 rounded-xl border px-3 py-2.5",
                files[input.slot] ? "border-brand-200 bg-brand-50/40" : "border-ink-200",
              )}
            >
              <span className="flex items-center gap-2 text-sm font-medium text-ink-900">
                {input.label}
                {input.required ? (
                  <span className="text-[11px] font-semibold text-danger-700">required</span>
                ) : (
                  <span className="text-[11px] text-ink-500">optional — its checks report “not run” without it</span>
                )}
              </span>
              <span className="text-xs text-ink-500">{SLOT_HINT[input.slot]}</span>
              <input
                type="file"
                accept=".csv,.txt,.xlsx"
                aria-label={input.label}
                className="mt-1 text-xs text-ink-700 file:mr-2 file:rounded-md file:border-0 file:bg-ink-100 file:px-2 file:py-1 file:text-xs file:font-medium"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  setFiles((prev) => ({ ...prev, [input.slot]: file }));
                }}
              />
            </label>
          ))}
        </div>

        <label className="flex items-start gap-2 text-sm text-ink-700">
          <input
            type="checkbox"
            className="mt-1"
            checked={usePrevious}
            onChange={(e) => setUsePrevious(e.target.checked)}
          />
          <span>
            With no previous-period file, compare against last month&apos;s <b>approved</b> check here.
            <span className="block text-xs text-ink-500">
              The report says where the comparison came from. Off, the month-on-month checks report “not run”.
            </span>
          </span>
        </label>

        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => run.mutate()} disabled={!ready || run.isPending}>
            {run.isPending ? <Loader2 size={14} className="animate-spin" /> : <UploadCloud size={14} />}
            Check the file
          </Button>
          <span className="text-xs text-ink-500">
            Files are read here and not kept: only their names, row counts and SHA-256 fingerprints are recorded.
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// One check
// ---------------------------------------------------------------------------
const VERDICT_LOOK: Record<Verdict, { wrap: string; tint: string; icon: typeof CheckCircle2; meaning: string }> = {
  CLEAR_TO_RELEASE: {
    wrap: "border-success-200 bg-success-50",
    tint: "text-success-800",
    icon: CheckCircle2,
    meaning: "Every check that ran passed or only raised flags. The clean file is the bank file as uploaded.",
  },
  RELEASE_WITH_HOLDS: {
    wrap: "border-warning-200 bg-warning-50",
    tint: "text-warning-900",
    icon: PauseCircle,
    meaning: "Some employees are held back. The clean file pays everyone else; the held lines are listed with their reasons.",
  },
  DO_NOT_RELEASE: {
    wrap: "border-danger-200 bg-danger-50",
    tint: "text-danger-800",
    icon: AlertOctagon,
    meaning: "A problem affects the whole file. There is no clean file: fix the cause and check again.",
  },
};

function RunView({ runId, onOpen }: { runId: string; onOpen: (id: string) => void }) {
  const detail = useQuery({ queryKey: ["dsb-run", runId], queryFn: () => fetchRun(runId) });
  if (detail.isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center gap-2 py-8 text-sm text-ink-500">
          <Loader2 className="animate-spin" size={15} /> Reading the check…
        </CardContent>
      </Card>
    );
  }
  if (detail.error || !detail.data) {
    return (
      <AlertBanner variant="error" title="Could not open this check">
        {detail.error instanceof Error ? detail.error.message : "Try again."}
      </AlertBanner>
    );
  }
  const run = detail.data;
  const look = VERDICT_LOOK[run.verdict];
  const Icon = look.icon;
  const t = run.totals;
  const stopped = run.verdict === "DO_NOT_RELEASE";
  const stops = run.report.findings.filter((f) => f.severity === "STOP_FILE");
  const unchecked = run.report.rules.filter((r) => r.status === "NOT_RUN" || r.status === "DISABLED");

  return (
    <div className="space-y-5">
      {run.superseded_by && (
        <AlertBanner variant="warning" title="A newer check of this month exists">
          This check cannot be approved.{" "}
          <button type="button" className="font-medium underline" onClick={() => onOpen(run.superseded_by!)}>
            Open the newer one
          </button>
          .
        </AlertBanner>
      )}

      <div className={cn("flex items-start gap-3 rounded-xl border px-5 py-4", look.wrap)}>
        <Icon size={26} className={cn("mt-0.5 shrink-0", look.tint)} />
        <div className="min-w-0 space-y-1">
          <p className={cn("text-lg font-semibold", look.tint)}>
            {VERDICT_TEXT[run.verdict]}
            {run.status === "approved" && " · approved"}
          </p>
          <p className="text-sm text-ink-700">{look.meaning}</p>
          <p className="text-xs text-ink-500">
            {run.bank_filename} · {run.period} · checked by {run.run_by}
            {run.created_at && ` at ${new Date(run.created_at).toLocaleString("en-IN")}`} · amounts checked against{" "}
            {t.amount_basis}
          </p>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label={stopped ? "Would be paid" : "To release"}
          value={money(t.release_amount)}
          qualifier={`${t.release_employees} employees`}
          tone={stopped ? "danger" : "success"}
        />
        <Stat
          label={stopped ? "Would be held" : "Held back"}
          value={money(t.held_amount)}
          qualifier={`${t.held_employees} employees`}
          tone={t.held_employees ? "warning" : "neutral"}
        />
        <Stat label="Flags to read" value={String(t.flags)} qualifier="hold no one" tone={t.flags ? "brand" : "neutral"} />
        <Stat
          label="Against last month"
          value={t.variance_vs_previous === null || stopped ? null : money(t.variance_vs_previous)}
          qualifier={
            t.previous_total === null
              ? "no previous period given"
              : `${t.variance_pct_vs_previous ?? 0}% · last month ${money(t.previous_total)} (${t.previous_total_basis})`
          }
        />
      </div>

      <Downloads run={run} />

      {unchecked.length > 0 && (
        <AlertBanner variant="warning" title={`${unchecked.length} check(s) did not run — these were NOT checked`}>
          <ul className="mt-1 space-y-1">
            {unchecked.map((r) => (
              <li key={r.rule_id}>
                <b>{r.rule_id}</b> {r.title} — {SEVERITY_TEXT[r.status as Severity]}: {r.reason}
              </li>
            ))}
          </ul>
        </AlertBanner>
      )}

      {stops.length > 0 && (
        <Card>
          <CardContent className="space-y-2 py-5">
            <h3 className="text-base font-semibold text-danger-800">Why this file must not be released</h3>
            <ul className="space-y-1.5 text-sm text-ink-800">
              {stops.map((f, i) => (
                <li key={`${f.rule_id}-${i}`}>
                  <b>{f.rule_id}</b>
                  {f.employee_id && ` · ${f.employee_id}`}: {f.reason}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {run.held.length > 0 && (
        <Card>
          <CardContent className="space-y-3 py-5">
            <h3 className="text-base font-semibold text-ink-900">
              {stopped ? "Would also be held" : "Held back"} — {run.held.length} employee(s), {money(t.held_amount)}
            </h3>
            <div className="divide-y divide-ink-200/70">
              {run.held.map((h) => (
                <div key={`${h.employee_id}-${h.rows.join(",")}`} className="py-2 text-sm">
                  <p className="font-medium text-ink-900">
                    {h.employee_id || "—"} {h.employee_name}{" "}
                    <span className="tabular-nums text-ink-600">· {money(h.amount)}</span>
                  </p>
                  <ul className="text-xs text-ink-600">
                    {h.reasons.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent className="py-5">
          <h3 className="pb-2 text-base font-semibold text-ink-900">From the register to the clean file</h3>
          <table className="w-full text-sm">
            <tbody className="divide-y divide-ink-200/60">
              {run.report.bridge.map((b) => (
                <tr key={b.label} className={b.total ? "font-semibold text-ink-900" : "text-ink-700"}>
                  <td className="py-1.5 pr-3">{b.label}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{money(b.amount)}</td>
                  <td className="w-16 py-1.5 text-right tabular-nums text-ink-500">{b.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      <FindingsTable findings={run.report.findings} />

      <ApprovalPanel run={run} />

      <details className="rounded-xl border border-ink-200 px-4 py-3 text-sm">
        <summary className="cursor-pointer font-medium text-ink-800">
          Files checked, and {run.report.notes.length} note(s) about their values
        </summary>
        <ul className="mt-2 space-y-1 text-xs text-ink-600">
          {run.report.inputs.map((i) => (
            <li key={i.slot}>
              <b>{i.label}</b>: {i.filename} · {i.rows ?? "—"} rows ·{" "}
              <span className="font-mono break-all">SHA-256 {i.sha256}</span>
            </li>
          ))}
        </ul>
        {run.report.notes.length > 0 && (
          <ul className="mt-3 max-h-64 space-y-1 overflow-y-auto text-xs text-ink-600">
            {run.report.notes.map((n, i) => (
              <li key={i}>
                {n.source}
                {n.row ? ` row ${n.row}` : ""}
                {n.employee_id ? ` · ${n.employee_id}` : ""}: {n.message}
              </li>
            ))}
          </ul>
        )}
      </details>
    </div>
  );
}

function Downloads({ run }: { run: RunDetail }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<DownloadKind | null>(null);
  const get = async (kind: DownloadKind) => {
    setBusy(kind);
    try {
      const { blob, filename } = await downloadRun(run.id, kind);
      saveBlob(blob, filename);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Download failed");
    } finally {
      setBusy(null);
    }
  };
  const stopped = run.verdict === "DO_NOT_RELEASE";
  return (
    <Card>
      <CardContent className="space-y-3 py-5">
        <div className="flex flex-wrap gap-2">
          <Button
            onClick={() => get("clean")}
            disabled={stopped || !run.clean_available || busy !== null}
            title={stopped ? "A stopped file has no clean copy" : undefined}
          >
            {busy === "clean" ? <Loader2 size={14} className="animate-spin" /> : <FileCheck2 size={14} />}
            Clean bank file
          </Button>
          {(["summary.pdf", "exceptions.xlsx", "exceptions.csv"] as DownloadKind[]).map((kind) => (
            <Button key={kind} variant="outline" onClick={() => get(kind)} disabled={busy !== null}>
              {busy === kind ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
              {kind === "summary.pdf" ? "Approver summary (PDF)" : kind === "exceptions.xlsx" ? "Exception report (Excel)" : "Exception report (CSV)"}
            </Button>
          ))}
        </div>
        {run.clean_sha256 && (
          <p className="text-xs text-ink-600">
            Clean file <b>{run.clean_filename}</b> · SHA-256{" "}
            <span className="font-mono break-all">{run.clean_sha256}</span>
          </p>
        )}
        {run.files_cleared_at ? (
          <p className="text-xs text-ink-500">
            The clean file was cleared after the retention period. The report and its fingerprints remain.
          </p>
        ) : (
          run.files_expire_at && (
            <p className="text-xs text-ink-500">
              The clean file is kept until {new Date(run.files_expire_at).toLocaleDateString("en-IN")}. Bank account
              numbers are shown in full in every download.
            </p>
          )
        )}
        {error && <p className="text-xs text-danger-700">{error}</p>}
      </CardContent>
    </Card>
  );
}

const SEVERITY_ORDER: Severity[] = ["STOP_FILE", "HOLD_ROW", "FLAG", "NOT_RUN", "DISABLED"];

function FindingsTable({ findings }: { findings: Finding[] }) {
  const [severity, setSeverity] = useState<Severity | "">("");
  const [rule, setRule] = useState("");
  const [query, setQuery] = useState("");
  const rules = useMemo(() => Array.from(new Set(findings.map((f) => f.rule_id))).sort(), [findings]);
  const shown = findings.filter(
    (f) =>
      (!severity || f.severity === severity) &&
      (!rule || f.rule_id === rule) &&
      (!query || `${f.employee_id} ${f.employee_name}`.toLowerCase().includes(query.toLowerCase())),
  );
  const counts = SEVERITY_ORDER.map((s) => [s, findings.filter((f) => f.severity === s).length] as const);
  return (
    <Card>
      <CardContent className="space-y-3 py-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold text-ink-900">Findings</h3>
            <p className="text-xs text-ink-500">
              {counts
                .filter(([, n]) => n)
                .map(([s, n]) => `${n} ${SEVERITY_TEXT[s].toLowerCase()}`)
                .join(" · ") || "Nothing found by the checks that ran."}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <select
              aria-label="Severity"
              value={severity}
              onChange={(e) => setSeverity(e.target.value as Severity | "")}
              className="h-8 rounded-lg border border-ink-200 bg-white px-2 text-xs"
            >
              <option value="">All severities</option>
              {SEVERITY_ORDER.map((s) => (
                <option key={s} value={s}>
                  {SEVERITY_TEXT[s]}
                </option>
              ))}
            </select>
            <select
              aria-label="Check"
              value={rule}
              onChange={(e) => setRule(e.target.value)}
              className="h-8 rounded-lg border border-ink-200 bg-white px-2 text-xs"
            >
              <option value="">All checks</option>
              {rules.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            <input
              aria-label="Employee"
              placeholder="Employee ID or name"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="h-8 w-44 rounded-lg border border-ink-200 bg-white px-2 text-xs"
            />
          </div>
        </div>
        {findings.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-xs">
              <thead>
                <tr className="text-left text-[11px] text-ink-500">
                  <th className="pb-1.5 pr-2 font-semibold">Check</th>
                  <th className="pb-1.5 pr-2 font-semibold">Severity</th>
                  <th className="pb-1.5 pr-2 font-semibold">Employee</th>
                  <th className="pb-1.5 pr-2 font-semibold">Expected</th>
                  <th className="pb-1.5 pr-2 font-semibold">Actual</th>
                  <th className="pb-1.5 pr-2 text-right font-semibold">Amount</th>
                  <th className="pb-1.5 font-semibold">Reason</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-200/60 align-top">
                {shown.slice(0, 300).map((f, i) => (
                  <tr key={`${f.rule_id}-${f.employee_id}-${i}`}>
                    <td className="whitespace-nowrap py-1.5 pr-2 font-medium text-ink-900">{f.rule_id}</td>
                    <td className="py-1.5 pr-2">
                      <span className={cn("whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold", SEVERITY_TONE[f.severity])}>
                        {SEVERITY_TEXT[f.severity]}
                      </span>
                    </td>
                    <td className="py-1.5 pr-2 text-ink-800">
                      {f.employee_id || "—"}
                      {f.employee_name && <span className="block text-ink-500">{f.employee_name}</span>}
                    </td>
                    <td className="py-1.5 pr-2 font-mono text-ink-700 [overflow-wrap:anywhere]">{f.expected || "—"}</td>
                    <td className="py-1.5 pr-2 font-mono text-ink-700 [overflow-wrap:anywhere]">{f.actual || "—"}</td>
                    <td className="whitespace-nowrap py-1.5 pr-2 text-right tabular-nums text-ink-700">{f.amount ? money(f.amount) : "—"}</td>
                    <td className="py-1.5 text-ink-700">{f.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {shown.length > 300 && (
              <p className="pt-2 text-xs text-ink-500">
                Showing 300 of {shown.length}. Every finding is in the exception report.
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ApprovalPanel({ run }: { run: RunDetail }) {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [name, setName] = useState("");
  const [acked, setAcked] = useState<string[]>([]);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const approve = useMutation({
    mutationFn: () =>
      approveRun(run.id, { approver_name: name, fingerprint: run.clean_sha256 ?? "", acknowledged: acked, comment }),
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["dsb-run", run.id] });
      queryClient.invalidateQueries({ queryKey: ["dsb-runs"] });
    },
    onError: (err: Error) => setError(err.message),
  });

  const a = run.approval;
  if (a) {
    return (
      <Card>
        <CardContent className="space-y-1 py-5 text-sm">
          <h3 className="flex items-center gap-2 text-base font-semibold text-success-800">
            <ShieldCheck size={17} /> Approved for release
          </h3>
          <p className="text-ink-700">
            By <b>{a.approver}</b> ({a.approver_email}
            {a.approver_role ? `, ${a.approver_role}` : ""})
            {a.approved_at && ` on ${new Date(a.approved_at).toLocaleString("en-IN")}`} — {money(a.release_amount)} to{" "}
            {a.release_employees} employees.
          </p>
          <p className="text-xs text-ink-600">
            Clean file SHA-256 <span className="font-mono break-all">{a.fingerprint}</span>
          </p>
          <p className="text-xs text-ink-600">
            {a.independent ? "Approved by someone other than the person who checked it." : "Checked and approved by the same person."}
            {a.independence_required ? " Your organisation requires a second person." : ""}
            {a.acknowledged.length > 0 && ` Acknowledged as not checked: ${a.acknowledged.join(", ")}.`}
          </p>
          {a.comment && <p className="text-xs text-ink-600">“{a.comment}”</p>}
          <p className="pt-1 text-xs text-ink-500">
            Approval is a record here. Upload the clean file to the bank yourself; check its SHA-256 matches.
          </p>
        </CardContent>
      </Card>
    );
  }
  if (run.verdict === "DO_NOT_RELEASE") return null;
  const self = run.independence_required && !!user?.email && user.email.toLowerCase() === run.run_by.toLowerCase();
  const allAcked = run.unchecked.every((r) => acked.includes(r));
  const blocked = !run.can_approve || self || Boolean(run.superseded_by) || !run.clean_available;

  return (
    <Card>
      <CardContent className="space-y-3 py-5">
        <h3 className="text-base font-semibold text-ink-900">Approve the release</h3>
        <p className="text-xs text-ink-600">
          You are approving the clean file with SHA-256{" "}
          <span className="font-mono break-all">{run.clean_sha256}</span> — {money(run.totals.release_amount)} to{" "}
          {run.totals.release_employees} employees. Nothing is sent: a person uploads this file to the bank.
        </p>
        {!run.can_approve && <p className="text-sm text-ink-600">Only an owner or manager can approve a release.</p>}
        {self && (
          <p className="text-sm text-warning-800">
            Your organisation requires a second person: you checked this file, so another owner or manager approves it.
          </p>
        )}
        {!blocked && (
          <>
            {run.unchecked.length > 0 && (
              <fieldset className="space-y-1.5 rounded-lg border border-warning-200 bg-warning-50/50 px-3 py-2">
                <legend className="px-1 text-xs font-semibold text-warning-900">
                  Acknowledge each check that did not run
                </legend>
                {run.report.rules
                  .filter((r) => run.unchecked.includes(r.rule_id))
                  .map((r) => (
                    <label key={r.rule_id} className="flex items-start gap-2 text-xs text-ink-800">
                      <input
                        type="checkbox"
                        className="mt-0.5"
                        checked={acked.includes(r.rule_id)}
                        onChange={(e) =>
                          setAcked((prev) =>
                            e.target.checked ? [...prev, r.rule_id] : prev.filter((x) => x !== r.rule_id),
                          )
                        }
                      />
                      <span>
                        I accept that <b>{r.rule_id}</b> {r.title} was not checked: {r.reason}
                      </span>
                    </label>
                  ))}
              </fieldset>
            )}
            <div className="flex flex-wrap items-end gap-3">
              <label>
                <span className="mb-1.5 block text-[11px] font-semibold text-ink-500">Your name, as you sign</span>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="h-9 w-64 rounded-lg border border-ink-200 bg-white px-3 text-sm"
                />
              </label>
              <label className="min-w-0 flex-1">
                <span className="mb-1.5 block text-[11px] font-semibold text-ink-500">Comment (optional)</span>
                <input
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  className="h-9 w-full rounded-lg border border-ink-200 bg-white px-3 text-sm"
                />
              </label>
              <Button onClick={() => approve.mutate()} disabled={name.trim().length < 2 || !allAcked || approve.isPending}>
                {approve.isPending ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />}
                Approve release
              </Button>
            </div>
          </>
        )}
        {error && <p className="text-xs text-danger-700">{error}</p>}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// History
// ---------------------------------------------------------------------------
function History({ onOpen, canOpen }: { onOpen: (id: string) => void; canOpen: boolean }) {
  const runs = useQuery({ queryKey: ["dsb-runs"], queryFn: () => fetchRuns() });
  if (runs.isLoading) return <p className="text-sm text-ink-500">Loading…</p>;
  const list = runs.data?.runs ?? [];
  if (!list.length) {
    return <p className="text-sm text-ink-500">No payment file has been checked for this company yet.</p>;
  }
  return (
    <Card>
      <CardContent className="overflow-x-auto py-5">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="text-left text-[11px] text-ink-500">
              <th className="pb-2 pr-3 font-semibold">Period</th>
              <th className="pb-2 pr-3 font-semibold">File</th>
              <th className="pb-2 pr-3 font-semibold">Verdict</th>
              <th className="pb-2 pr-3 text-right font-semibold">To release</th>
              <th className="pb-2 pr-3 text-right font-semibold">Held</th>
              <th className="pb-2 pr-3 font-semibold">Not checked</th>
              <th className="pb-2 pr-3 font-semibold">Status</th>
              <th className="pb-2 font-semibold">Checked</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-200/60">
            {list.map((r) => (
              <tr key={r.id}>
                <td className="py-2 pr-3">{r.period}</td>
                <td className="py-2 pr-3">
                  {canOpen ? (
                    <button type="button" onClick={() => onOpen(r.id)} className="font-medium text-brand-700 hover:underline">
                      {r.bank_filename}
                    </button>
                  ) : (
                    r.bank_filename
                  )}
                </td>
                <td className="py-2 pr-3">{VERDICT_TEXT[r.verdict]}</td>
                <td className="py-2 pr-3 text-right tabular-nums">
                  {r.verdict === "DO_NOT_RELEASE" ? "—" : money(r.totals.release_amount)}
                </td>
                <td className="py-2 pr-3 text-right tabular-nums">{r.totals.held_employees}</td>
                <td className="py-2 pr-3 text-xs">{r.unchecked.join(", ") || "—"}</td>
                <td className="py-2 pr-3">
                  {r.approval ? `Approved by ${r.approval.approver}` : r.status === "checked" ? "Not approved" : r.status}
                </td>
                <td className="py-2 text-xs text-ink-600">
                  {r.run_by}
                  {r.created_at && <span className="block">{new Date(r.created_at).toLocaleString("en-IN")}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------
const NUMBER_SETTINGS: { key: string; label: string; hint: string }[] = [
  { key: "variance_pct", label: "Change against last month (%)", hint: "DSB-13 flags a salary that moved more than this." },
  { key: "name_similarity", label: "Name similarity (0–1)", hint: "DSB-14: beneficiary name against the register." },
  { key: "account_length_min", label: "Shortest account number", hint: "DSB-12" },
  { key: "account_length_max", label: "Longest account number", hint: "DSB-12" },
  { key: "amount_tolerance", label: "Per-employee tolerance (₹)", hint: "DSB-08, DSB-17. Default ₹0.00: to the paisa." },
  { key: "total_tolerance", label: "File total tolerance (₹)", hint: "DSB-01" },
  { key: "max_hold_share_pct", label: "Most of the file that may be held (%)", hint: "Above this the whole file stops (DSB-01, DSB-02). 0 = no limit." },
  { key: "debit_account", label: "Company debit account", hint: "DSB-04 compares the file header against this. Blank: DSB-04 does not run." },
];

function SettingsPanel({ catalogue, canEdit }: { catalogue: Catalogue; canEdit: boolean }) {
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ["dsb-settings"], queryFn: fetchSettings });
  const [draft, setDraft] = useState<Settings | null>(null);
  const [custom, setCustom] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  useEffect(() => {
    if (settings.data) {
      setDraft(settings.data);
      setCustom(
        JSON.stringify({ profiles: settings.data.custom_profiles, templates: settings.data.custom_templates }, null, 2),
      );
    }
  }, [settings.data]);
  const save = useMutation({
    mutationFn: async () => {
      if (!draft) throw new Error("Nothing to save");
      let parsed: { profiles?: Record<string, unknown>; templates?: Record<string, unknown> };
      try {
        parsed = JSON.parse(custom || "{}");
      } catch {
        throw new Error("Your own layouts are not valid JSON.");
      }
      return saveSettings({
        profile_key: draft.profile_key,
        template_key: draft.template_key,
        overrides: draft.overrides,
        custom_profiles: parsed.profiles ?? {},
        custom_templates: parsed.templates ?? {},
      });
    },
    onSuccess: () => {
      setMessage({ ok: true, text: "Saved. The next check uses these settings, and records them." });
      queryClient.invalidateQueries({ queryKey: ["dsb-settings"] });
      queryClient.invalidateQueries({ queryKey: ["dsb-catalogue"] });
    },
    onError: (err: Error) => setMessage({ ok: false, text: err.message }),
  });
  if (!draft) return <p className="text-sm text-ink-500">Loading…</p>;
  const o = draft.overrides;
  const set = (patch: Partial<Settings["overrides"]>) => setDraft({ ...draft, overrides: { ...o, ...patch } });
  const value = (key: string) => {
    const v = o[key] ?? catalogue.defaults[key];
    return v === null || v === undefined ? "" : String(v);
  };

  return (
    <div className="space-y-5">
      {!canEdit && (
        <AlertBanner variant="info" title="Read only">
          These settings decide whose salary is held, so only an owner or manager changes them.
        </AlertBanner>
      )}
      <fieldset disabled={!canEdit} className="space-y-5">
        <Card>
          <CardContent className="space-y-4 py-5">
            <div className="flex flex-wrap gap-3">
              <label>
                <span className="mb-1.5 block text-[11px] font-semibold text-ink-500">Column layout (profile)</span>
                <select
                  value={draft.profile_key}
                  onChange={(e) => setDraft({ ...draft, profile_key: e.target.value })}
                  className="h-9 rounded-lg border border-ink-200 bg-white px-3 text-sm"
                >
                  {catalogue.profiles.map((p) => (
                    <option key={p.key} value={p.key}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span className="mb-1.5 block text-[11px] font-semibold text-ink-500">Bank file layout</span>
                <select
                  value={draft.template_key ?? ""}
                  onChange={(e) => setDraft({ ...draft, template_key: e.target.value || null })}
                  className="h-9 rounded-lg border border-ink-200 bg-white px-3 text-sm"
                >
                  <option value="">The profile&apos;s own</option>
                  {catalogue.templates.map((t) => (
                    <option key={t.key} value={t.key}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <p className="text-xs text-ink-500">
              The built-in layouts are examples made from synthetic files. None is any bank&apos;s official format:
              check yours against your bank&apos;s specification.
            </p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {NUMBER_SETTINGS.map((s) => (
                <label key={s.key}>
                  <span className="mb-1 block text-[11px] font-semibold text-ink-500">{s.label}</span>
                  <input
                    value={value(s.key)}
                    onChange={(e) => set({ [s.key]: e.target.value === "" ? null : e.target.value })}
                    className="h-9 w-full rounded-lg border border-ink-200 bg-white px-3 text-sm"
                  />
                  <span className="mt-0.5 block text-[11px] text-ink-500">{s.hint}</span>
                </label>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="overflow-x-auto py-5">
            <h3 className="pb-2 text-base font-semibold text-ink-900">Checks</h3>
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="text-left text-[11px] text-ink-500">
                  <th className="pb-2 pr-3 font-semibold">Check</th>
                  <th className="pb-2 pr-3 font-semibold">On</th>
                  <th className="pb-2 font-semibold">When it finds something</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-200/60">
                {catalogue.rules.map((r) => {
                  const enabled = o.enabled?.[r.rule_id] ?? true;
                  const severity = o.severities?.[r.rule_id] ?? r.default_severity;
                  return (
                    <tr key={r.rule_id}>
                      <td className="py-1.5 pr-3">
                        <b>{r.rule_id}</b> {r.title}
                      </td>
                      <td className="py-1.5 pr-3">
                        <input
                          type="checkbox"
                          aria-label={`${r.rule_id} on`}
                          checked={enabled}
                          onChange={(e) => {
                            const next = { ...(o.enabled ?? {}) };
                            if (e.target.checked) delete next[r.rule_id];
                            else next[r.rule_id] = false;
                            set({ enabled: next });
                          }}
                        />
                      </td>
                      <td className="py-1.5">
                        <select
                          aria-label={`${r.rule_id} severity`}
                          value={severity}
                          disabled={!enabled}
                          onChange={(e) => {
                            const next = { ...(o.severities ?? {}) };
                            if (e.target.value === r.default_severity) delete next[r.rule_id];
                            else next[r.rule_id] = e.target.value as Severity;
                            set({ severities: next });
                          }}
                          className="h-8 rounded-lg border border-ink-200 bg-white px-2 text-xs"
                        >
                          {r.allowed.map((s) => (
                            <option key={s} value={s}>
                              {SEVERITY_TEXT[s]}
                              {s === r.default_severity ? " (default)" : ""}
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="pt-2 text-xs text-ink-500">
              A check switched off is still listed with every result, as “switched off”, and must be acknowledged before
              approval.
            </p>
          </CardContent>
        </Card>

        <details className="rounded-xl border border-ink-200 px-4 py-3">
          <summary className="cursor-pointer text-sm font-medium text-ink-800">Your own layouts (JSON)</summary>
          <p className="mt-2 text-xs text-ink-500">
            A profile maps your column names; a template describes your bank file. Same shape as the built-in ones —
            see the implementation manual. Refused with a reason if anything is wrong.
          </p>
          <textarea
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
            rows={10}
            className="mt-2 w-full rounded-lg border border-ink-200 bg-white p-2 font-mono text-xs"
          />
        </details>
      </fieldset>

      {canEdit && (
        <div className="flex items-center gap-3">
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            {save.isPending && <Loader2 size={14} className="animate-spin" />}
            Save settings
          </Button>
          {draft.updated_by && (
            <span className="text-xs text-ink-500">
              Last changed by {draft.updated_by}
              {draft.updated_at && ` on ${new Date(draft.updated_at).toLocaleString("en-IN")}`}
            </span>
          )}
        </div>
      )}
      {message && (
        <AlertBanner variant={message.ok ? "success" : "error"} title={message.ok ? "Saved" : "Not saved"}>
          {message.text}
        </AlertBanner>
      )}
      <p className="text-xs text-ink-500">
        Whether the person who checked a file may also approve it is set under Team &amp; invitations → approval
        controls{draft.independence_required ? " (currently: a second person is required)" : " (currently: one person may do both)"}.
      </p>
    </div>
  );
}
