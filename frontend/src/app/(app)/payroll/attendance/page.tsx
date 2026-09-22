"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  Loader2,
  ShieldCheck,
  UploadCloud,
} from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import { formatINR } from "@/lib/cost-analysis";
import {
  ATTENDANCE_TEMPLATE,
  SEVERITY_TONE,
  commitAttendance,
  fetchAttendanceRegisters,
  fetchPaidDayBases,
  validateAttendance,
  type AttendanceCheck,
  type AttendanceFinding,
} from "@/lib/attendance";
import { cn } from "@/lib/utils";

function currentPeriod(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

/**
 * Attendance upload, checked before it is stored.
 *
 * Deliberately two steps. Attendance is the input payroll multiplies, so a
 * wrong day count becomes a wrong payslip that every register-level check will
 * pass — the register ends up perfectly consistent with the wrong number of
 * days. Checking the file first costs nothing; finding out afterwards costs a
 * correction cycle.
 */
export default function AttendancePage() {
  const queryClient = useQueryClient();
  const [period, setPeriod] = useState(currentPeriod());
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [check, setCheck] = useState<AttendanceCheck | null>(null);
  const [stored, setStored] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: bases } = useQuery({ queryKey: ["paid-day-bases"], queryFn: fetchPaidDayBases });
  const { data: registers } = useQuery({
    queryKey: ["attendance-registers"],
    queryFn: fetchAttendanceRegisters,
  });

  const run = useMutation({
    mutationFn: () => validateAttendance(file as File, period),
    onSuccess: (result) => {
      setError(null);
      setStored(null);
      setCheck(result);
    },
    onError: (err: Error) => {
      setCheck(null);
      setError(err.message);
    },
  });

  const commit = useMutation({
    mutationFn: () => commitAttendance(file as File, period),
    onSuccess: (result) => {
      setError(null);
      setStored(
        `Stored ${result.rows_stored} of ${result.rows_read} rows for ${result.period_month.slice(0, 7)}.`,
      );
      queryClient.invalidateQueries({ queryKey: ["attendance-registers"] });
    },
    onError: (err: Error) => setError(err.message),
  });

  function pick(next: File | null) {
    setFile(next);
    setCheck(null);
    setStored(null);
    setError(null);
  }

  const basis = bases?.bases.find((b) => b.key === check?.paid_days_basis);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Attendance"
        description="The days payroll multiplies. Checked against itself before it is stored, and against pay when the register is validated."
      />

      {error && (
        <AlertBanner variant="error" title="That file could not be read">
          {error}
        </AlertBanner>
      )}
      {stored && (
        <AlertBanner variant="success" title="Stored">
          {stored} Validate the salary register for this month and the attendance rules
          will run against it.
        </AlertBanner>
      )}

      <Card>
        <CardContent className="space-y-4 py-5">
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                Period
              </span>
              <input
                type="month"
                value={period}
                onChange={(event) => {
                  setPeriod(event.target.value);
                  setCheck(null);
                }}
                className="h-9 rounded-lg border border-ink-200 bg-white px-3 text-sm text-ink-900 dark:border-ink-700 dark:bg-ink-900 dark:text-white"
              />
            </div>
            <a
              href={`data:text/csv;charset=utf-8,${encodeURIComponent(ATTENDANCE_TEMPLATE)}`}
              download="attendance-template.csv"
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-ink-200 px-3 text-sm font-medium text-ink-700 transition hover:bg-ink-50 dark:border-ink-700 dark:text-ink-200 dark:hover:bg-ink-800"
            >
              <Download size={14} /> Template
            </a>
          </div>

          <label
            onDragOver={(event) => {
              event.preventDefault();
              setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDrag(false);
              pick(event.dataTransfer.files?.[0] ?? null);
            }}
            className={cn(
              "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition",
              drag
                ? "border-brand-500 bg-brand-50/60 dark:bg-brand-500/10"
                : "border-ink-200 hover:border-ink-300 dark:border-ink-700",
            )}
          >
            {file ? (
              <>
                <FileSpreadsheet size={22} className="text-brand-600 dark:text-brand-300" />
                <span className="text-sm font-medium text-ink-900 dark:text-white">
                  {file.name}
                </span>
                <span className="text-xs text-ink-500 dark:text-ink-400">
                  Choose another to replace it
                </span>
              </>
            ) : (
              <>
                <UploadCloud size={22} className="text-ink-400" />
                <span className="text-sm font-medium text-ink-800 dark:text-ink-100">
                  Drop the attendance file, or choose one
                </span>
                <span className="text-xs text-ink-500 dark:text-ink-400">
                  .csv or .xlsx — present, paid, loss of pay, overtime
                </span>
              </>
            )}
            <input
              type="file"
              accept=".csv,.xlsx"
              className="hidden"
              onChange={(event) => pick(event.target.files?.[0] ?? null)}
            />
          </label>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => run.mutate()}
              disabled={!file || run.isPending}
              className="inline-flex h-9 items-center gap-2 rounded-lg bg-brand-600 px-3 text-sm font-medium text-white transition hover:bg-brand-700 disabled:opacity-50"
            >
              {run.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <ShieldCheck size={14} />
              )}
              Check the file
            </button>
            <button
              type="button"
              onClick={() => commit.mutate()}
              disabled={!file || !check || commit.isPending}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-ink-200 px-3 text-sm font-medium text-ink-700 transition hover:bg-ink-50 disabled:opacity-50 dark:border-ink-700 dark:text-ink-200 dark:hover:bg-ink-800"
            >
              {commit.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <CheckCircle2 size={14} />
              )}
              Store for {period}
            </button>
            {check && !check.clean && (
              <span className="text-xs text-ink-500 dark:text-ink-400">
                You can store it anyway — the problems stay on the record.
              </span>
            )}
          </div>
        </CardContent>
      </Card>

      {check && (
        <>
          <Verdict check={check} />

          <Card>
            <CardContent className="py-5">
              <div className="grid gap-3 sm:grid-cols-3">
                <Figure label="Employees" value={`${check.employees}`} />
                <Figure
                  label="Rows read"
                  value={`${check.row_count}`}
                  hint={
                    check.row_count === check.employees
                      ? undefined
                      : "more rows than employees — see duplicates below"
                  }
                />
                <Figure
                  label="Daily rate basis"
                  value={basis?.label ?? check.paid_days_basis}
                  hint={basis?.hint}
                />
              </div>

              {check.unmapped_columns.length > 0 && (
                <p className="pt-4 text-xs text-ink-500 dark:text-ink-400">
                  Columns this product did not recognise and will ignore:{" "}
                  <span className="font-medium">{check.unmapped_columns.join(", ")}</span>
                </p>
              )}
            </CardContent>
          </Card>

          {check.findings.length > 0 && (
            <Card>
              <CardContent className="py-5">
                <h3 className="pb-1 text-base font-semibold text-ink-900 dark:text-white">
                  What does not add up
                </h3>
                <p className="pb-3 text-xs text-ink-500 dark:text-ink-400">
                  Judged on the file alone. Pay is checked against these days when the
                  salary register for the month is validated.
                </p>
                <div className="space-y-2">
                  {check.findings.map((finding, index) => (
                    <FindingRow key={`${finding.rule_id}-${finding.employee_id}-${index}`} finding={finding} />
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}

      <Card>
        <CardContent className="py-5">
          <h3 className="flex items-center gap-2 pb-3 text-base font-semibold text-ink-900 dark:text-white">
            <CalendarDays size={16} className="text-ink-400" /> Stored months
          </h3>
          {registers?.length ? (
            <div className="divide-y divide-ink-200/70 dark:divide-ink-700/60">
              {registers.map((register) => (
                <div
                  key={register.id}
                  className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm"
                >
                  <span className="text-ink-800 dark:text-ink-100">
                    {register.period_month.slice(0, 7)} · {register.filename}
                  </span>
                  <span className="text-xs tabular-nums text-ink-500 dark:text-ink-400">
                    {register.employee_count} employees
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-ink-500 dark:text-ink-400">
              None yet. Until a month is stored, the attendance rules stay silent rather
              than reporting every employee as unverifiable.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Verdict({ check }: { check: AttendanceCheck }) {
  if (check.clean) {
    return (
      <div className="flex items-start gap-3 rounded-xl border border-success-200/80 bg-success-50/60 px-4 py-3 dark:border-success-500/25 dark:bg-success-500/10">
        <CheckCircle2 size={17} className="mt-0.5 shrink-0 text-success-700 dark:text-success-300" />
        <div className="space-y-0.5">
          <p className="text-sm font-semibold text-success-700 dark:text-success-300">
            The file adds up
          </p>
          <p className="text-xs text-ink-600 dark:text-ink-300">
            Every row reconciles against the month. This says nothing yet about whether
            pay followed from it — that is checked when the register is validated.
          </p>
        </div>
      </div>
    );
  }
  const critical = check.counts.by_severity.CRITICAL ?? 0;
  return (
    <div className="flex items-start gap-3 rounded-xl border border-danger-200/80 bg-danger-50/60 px-4 py-3 dark:border-danger-500/25 dark:bg-danger-500/10">
      <AlertTriangle size={17} className="mt-0.5 shrink-0 text-danger-700 dark:text-danger-300" />
      <div className="space-y-0.5">
        <p className="text-sm font-semibold text-danger-700 dark:text-danger-300">
          {check.counts.total} problem(s) in this file
          {critical > 0 && `, ${critical} critical`}
        </p>
        <p className="text-xs text-ink-600 dark:text-ink-300">
          A file that does not add up cannot be reconciled against payroll. Fix it and
          re-check, or store it and carry the problems on the record.
        </p>
      </div>
    </div>
  );
}

function FindingRow({ finding }: { finding: AttendanceFinding }) {
  return (
    <div className="rounded-xl border border-ink-200/70 px-4 py-3 dark:border-ink-700/60">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
            SEVERITY_TONE[finding.severity] ?? SEVERITY_TONE.INFO,
          )}
        >
          {finding.severity}
        </span>
        <span className="text-sm font-semibold text-ink-900 dark:text-white">
          {finding.rule_name}
        </span>
        <span className="text-xs text-ink-500 dark:text-ink-400">
          {finding.employee_id}
          {finding.employee_name ? ` · ${finding.employee_name}` : ""}
        </span>
        {finding.financial_impact > 0 && (
          <span className="ml-auto text-xs font-semibold tabular-nums text-danger-600 dark:text-danger-400">
            {formatINR(finding.financial_impact)}
          </span>
        )}
      </div>
      <p className="pt-1 text-xs text-ink-600 dark:text-ink-300">{finding.reason}</p>
      {finding.suggested_fix && (
        <p className="pt-1 text-xs text-ink-500 dark:text-ink-400">{finding.suggested_fix}</p>
      )}
    </div>
  );
}

function Figure({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <span className="block text-[10px] font-semibold uppercase tracking-wide text-ink-400">
        {label}
      </span>
      <p className="font-display text-xl font-semibold tabular-nums text-ink-900 dark:text-white">
        {value}
      </p>
      {hint && <p className="pt-0.5 text-xs text-ink-500 dark:text-ink-400">{hint}</p>}
    </div>
  );
}
