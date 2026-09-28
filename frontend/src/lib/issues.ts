/**
 * The issue worklist: findings as work to be done, not rows in a run.
 *
 * A finding is keyed by its fingerprint (company + employee + rule +
 * component), so an exception explained in April is still explained in
 * September. Each one can carry an owner, a due date, comments and evidence,
 * and every decision on it is kept.
 */
import { apiBlob, apiFetch, parseEnvelopeResponse } from "@/lib/api";
import type { Page } from "@/lib/validation";

export type IssueState = "open" | "acknowledged" | "waived" | "resolved";

export type Issue = {
  id: string;
  fingerprint: string;
  employee_id: string;
  employee_name: string | null;
  rule_id: string;
  rule_name: string;
  component: string | null;
  severity: "CRITICAL" | "WARNING" | "INFO";
  state: IssueState;
  first_seen_period: string;
  last_seen_period: string;
  occurrence_count: number;
  last_financial_impact: number;
  impact_calculated: boolean;
  resolved_period: string | null;
  note: string | null;
  waiver_reason: string | null;
  waived_until: string | null;
  waiver_open_ended: boolean;
  decided_at: string | null;
  owner_user_id: string | null;
  owner_email: string | null;
  due_date: string | null;
  overdue: boolean;
  comment_count: number;
  attachment_count: number;
};

export type IssuePage = Page<Issue> & {
  counts: Record<IssueState, number>;
  overdue: number;
  unassigned: number;
  rules: { rule_id: string; rule_name: string; count: number }[];
};

export type IssueEvent = {
  id: string;
  from_state: string | null;
  to_state: string;
  reason: string | null;
  waived_until: string | null;
  actor_email: string | null;
  created_at: string | null;
};

export type IssueComment = {
  id: string;
  body: string;
  author_email: string | null;
  created_at: string | null;
};

export type IssueAttachment = {
  id: string;
  filename: string;
  content_type: string;
  size: number;
  sha256: string;
  uploaded_by_email: string | null;
  created_at: string | null;
};

export type IssueDetail = {
  finding: Issue;
  history: IssueEvent[];
  comments: IssueComment[];
  attachments: IssueAttachment[];
};

export type Assignee = { user_id: string; email: string; role: string };

export type WorklistParams = {
  page?: number;
  page_size?: number;
  state?: IssueState | "active" | "";
  severity?: string;
  rule_id?: string;
  owner?: "me" | "none" | string;
  overdue?: boolean;
  recurring?: boolean;
  q?: string;
  sort?: "priority" | "due_date" | "impact" | "last_seen";
};

export type BulkAction =
  | { action: "decision"; state: IssueState; reason?: string | null; waived_until?: string | null; note?: string | null }
  | { action: "assign"; owner_user_id: string | null; due_date?: string | null };

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "" || v === false) continue;
    p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

const fp = (fingerprint: string) => encodeURIComponent(fingerprint);

async function send<T>(path: string, method: string, body?: unknown): Promise<T> {
  return parseEnvelopeResponse<T>(
    await apiFetch(path, { method, body: body === undefined ? undefined : JSON.stringify(body) }),
  );
}

export const issuesApi = {
  worklist: (params: WorklistParams = {}) =>
    send<IssuePage>(`/api/findings/worklist${qs(params)}`, "GET"),
  detail: (fingerprint: string) => send<IssueDetail>(`/api/findings/${fp(fingerprint)}`, "GET"),
  decide: (fingerprint: string, body: { state: IssueState; reason?: string | null; waived_until?: string | null; note?: string | null }) =>
    send<Issue>(`/api/findings/${fp(fingerprint)}/decision`, "POST", body),
  assign: (fingerprint: string, body: { owner_user_id: string | null; due_date: string | null }) =>
    send<Issue>(`/api/findings/${fp(fingerprint)}/assignment`, "PATCH", body),
  comment: (fingerprint: string, body: string) =>
    send<IssueComment>(`/api/findings/${fp(fingerprint)}/comments`, "POST", { body }),
  attach: async (fingerprint: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return parseEnvelopeResponse<IssueAttachment>(
      await apiFetch(`/api/findings/${fp(fingerprint)}/attachments`, { method: "POST", body: form }),
    );
  },
  download: (fingerprint: string, attachmentId: string) =>
    apiBlob(`/api/findings/${fp(fingerprint)}/attachments/${encodeURIComponent(attachmentId)}`),
  bulk: (fingerprints: string[], action: BulkAction) =>
    send<{ updated: number; skipped: { fingerprint: string; reason: string }[] }>(
      "/api/findings/bulk", "POST", { fingerprints, ...action },
    ),
  assignees: () => send<Assignee[]>("/api/findings/assignees", "GET"),
};

export const ISSUE_STATE_LABEL: Record<IssueState, string> = {
  open: "Open",
  acknowledged: "In progress",
  waived: "Waived",
  resolved: "Resolved",
};
