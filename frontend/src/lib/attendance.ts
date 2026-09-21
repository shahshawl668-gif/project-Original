import { apiFetch, parseEnvelopeResponse } from "@/lib/api";

/**
 * Attendance, and the pay that should follow from it.
 *
 * Two calls matter and they do different jobs. `validateAttendance` checks a
 * file against itself and stores nothing — run it first, because a file that
 * does not add up is not a file anyone can reconcile payroll against.
 * `commitAttendance` stores it, and reports the same problems again alongside
 * what it actually kept.
 */

export type AttendanceFinding = {
  employee_id: string;
  employee_name: string;
  rule_id: string;
  rule_name: string;
  component: string;
  expected_value: string;
  actual_value: string;
  difference: string;
  severity: "CRITICAL" | "WARNING" | "INFO";
  status: string;
  reason: string;
  suggested_fix: string;
  financial_impact: number;
};

export type AttendanceCheck = {
  period_month: string;
  filename: string | null;
  row_count: number;
  employees: number;
  recognised_columns: string[];
  unmapped_columns: string[];
  paid_days_basis: string;
  counts: { total: number; by_severity: Record<string, number> };
  findings: AttendanceFinding[];
  clean: boolean;
};

export type AttendanceCommit = {
  id: string;
  period_month: string;
  filename: string | null;
  employee_count: number;
  rows_read: number;
  rows_stored: number;
  problems: AttendanceFinding[];
};

export type AttendanceRegisterMeta = {
  id: string;
  period_month: string;
  filename: string | null;
  employee_count: number;
  created_at: string | null;
};

export type BasisMeta = { key: string; label: string; hint: string };

export function validateAttendance(file: File, period: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("meta", JSON.stringify({ period_month: `${period}-01` }));
  return apiFetch("/api/workforce/attendance/validate", { method: "POST", body: form }).then(
    (r) => parseEnvelopeResponse<AttendanceCheck>(r),
  );
}

export function commitAttendance(file: File, period: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("meta", JSON.stringify({ period_month: `${period}-01` }));
  return apiFetch("/api/workforce/attendance/commit", { method: "POST", body: form }).then((r) =>
    parseEnvelopeResponse<AttendanceCommit>(r),
  );
}

export function fetchAttendanceRegisters() {
  return apiFetch("/api/workforce/attendance").then((r) =>
    parseEnvelopeResponse<AttendanceRegisterMeta[]>(r),
  );
}

export function fetchPaidDayBases() {
  return apiFetch("/api/workforce/attendance/bases").then((r) =>
    parseEnvelopeResponse<{ bases: BasisMeta[] }>(r),
  );
}

export const SEVERITY_TONE: Record<string, string> = {
  CRITICAL: "bg-danger-500/10 text-danger-700 ring-1 ring-danger-500/30 dark:text-danger-300",
  WARNING: "bg-warning-500/10 text-warning-800 ring-1 ring-warning-500/30 dark:text-warning-200",
  INFO: "bg-ink-500/10 text-ink-600 ring-1 ring-ink-500/20 dark:text-ink-300",
};

/** The template this product reads, for a client who has no export yet. */
export const ATTENDANCE_TEMPLATE =
  "employee_id,employee_name,calendar_days,present_days,paid_leave_days," +
  "weekly_off_days,holiday_days,lop_days,paid_days,overtime_hours\n" +
  "E001,Asha Menon,30,22,1,4,1,2,28,0\n" +
  "E002,Rahul Verma,30,25,0,4,1,0,30,10\n";
