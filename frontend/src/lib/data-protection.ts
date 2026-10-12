import { apiJson } from "@/lib/api";

export type RetentionPolicy = {
  payroll_months: number | null;
  min_months: number;
  max_months: number;
  reason: string | null;
  set_by: string | null;
  set_at: string | null;
  last_applied_at: string | null;
  last_applied: { keep_from?: string; counts?: Record<string, number> };
  status: "set" | "not_set";
  statement: string;
  pending?: { keep_from: string; counts: Record<string, number> };
};

export type RetainedRecord = { store: string; count: number; why: string };

export type ErasurePlan = {
  employee_id: string;
  counts: Record<string, number>;
  retained: RetainedRecord[];
};

export type ErasureRequest = {
  id: string;
  employee_id: string;
  reason: string;
  requested_by: string;
  completed_at: string | null;
  counts: Record<string, number>;
  retained: RetainedRecord[];
};

const BASE = "/api/data-protection";

export const dataProtection = {
  policy: () => apiJson<RetentionPolicy>(`${BASE}/retention`),
  previewRetention: (months: number) =>
    apiJson<{ keep_from: string; counts: Record<string, number> }>(`${BASE}/retention/preview?months=${months}`),
  setRetention: (payroll_months: number | null, reason: string) =>
    apiJson<RetentionPolicy>(`${BASE}/retention`, {
      method: "PUT",
      body: JSON.stringify({ payroll_months, reason }),
    }),
  applyRetention: () =>
    apiJson<{ counts: Record<string, number>; policy: RetentionPolicy }>(`${BASE}/retention/apply`, { method: "POST" }),
  erasures: () => apiJson<ErasureRequest[]>(`${BASE}/erasures`),
  previewErasure: (employeeId: string) =>
    apiJson<ErasurePlan>(`${BASE}/erasures/preview?employee_id=${encodeURIComponent(employeeId)}`),
  erase: (employee_id: string, confirm_employee_id: string, reason: string) =>
    apiJson<ErasureRequest>(`${BASE}/erasures`, {
      method: "POST",
      body: JSON.stringify({ employee_id, confirm_employee_id, reason }),
    }),
};
