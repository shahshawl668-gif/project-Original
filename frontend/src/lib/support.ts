import { apiFetch, parseEnvelopeResponse } from "@/lib/api";

/**
 * Break-glass support access, from both sides.
 *
 * The client's side is the one that matters: they see every session, can revoke
 * one instantly, and own the policy that decides whether sessions can be opened
 * at all.
 */

export type SupportPolicy = "break_glass" | "approval_required" | "disabled";

export type SupportGrant = {
  id: string;
  org_id?: string;
  organization?: string;
  admin_email: string | null;
  reason: string;
  state: "pending" | "active" | "ended" | "revoked" | "expired";
  policy_at_grant?: SupportPolicy;
  read_only: boolean;
  identity_masked: boolean;
  requested_at?: string | null;
  expires_at: string | null;
  approved_by?: string | null;
  approved_at?: string | null;
  ended_at?: string | null;
  ended_by?: string | null;
  ended_reason?: string | null;
  last_used_at?: string | null;
  use_count?: number;
};

export type SupportStatus = {
  policy: SupportPolicy;
  policies: { key: SupportPolicy; label: string; hint: string }[];
  active: SupportGrant[];
  history: SupportGrant[];
  always_true: string[];
};

export type SupportOrg = {
  id: string;
  name: string;
  org_type: string;
  support_access_policy: SupportPolicy;
};

/** Any member can see whether someone is looking right now. */
export const fetchActiveSupport = () =>
  apiFetch("/api/org/support/active").then((r) =>
    parseEnvelopeResponse<{ active: SupportGrant[] }>(r),
  );

/** Owners and managers see the policy and the full history. */
export const fetchSupportStatus = () =>
  apiFetch("/api/org/support").then((r) => parseEnvelopeResponse<SupportStatus>(r));

export const setSupportPolicy = (policy: SupportPolicy) =>
  apiFetch("/api/org/support/policy", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ policy }),
  }).then((r) => parseEnvelopeResponse<{ policy: SupportPolicy }>(r));

export const revokeSupport = (id: string) =>
  apiFetch(`/api/org/support/grants/${id}/revoke`, { method: "POST" }).then((r) =>
    parseEnvelopeResponse<SupportGrant>(r),
  );

export const approveSupport = (id: string) =>
  apiFetch(`/api/org/support/grants/${id}/approve`, { method: "POST" }).then((r) =>
    parseEnvelopeResponse<SupportGrant>(r),
  );

// ---- platform side --------------------------------------------------------
export const fetchSupportOrgs = () =>
  apiFetch("/api/admin/support/organizations").then((r) =>
    parseEnvelopeResponse<SupportOrg[]>(r),
  );

export const fetchMyGrants = () =>
  apiFetch("/api/admin/support/grants?mine=true").then((r) =>
    parseEnvelopeResponse<SupportGrant[]>(r),
  );

export const openSupport = (body: { org_id: string; reason: string; minutes: number }) =>
  apiFetch("/api/admin/support/grants", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => parseEnvelopeResponse<SupportGrant>(r));

export const endSupport = (id: string, reason: string) =>
  apiFetch(`/api/admin/support/grants/${id}/end`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  }).then((r) => parseEnvelopeResponse<SupportGrant>(r));

/** How long is left, in words. Never negative — an elapsed session is over. */
export function timeLeft(expiresAt: string | null): string {
  if (!expiresAt) return "—";
  const ms = new Date(expiresAt).getTime() - Date.now();
  if (ms <= 0) return "expired";
  const minutes = Math.round(ms / 60000);
  if (minutes < 60) return `${minutes} min left`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m left`;
}
