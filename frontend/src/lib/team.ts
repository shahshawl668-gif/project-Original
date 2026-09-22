import { apiFetch, parseEnvelopeResponse, setTokens } from "@/lib/api";

/**
 * Members of an organization, and the invitations that put them there.
 *
 * Two shapes are deliberately asymmetric. `Invitation` carries a token only on
 * the response that created it — the API stores a hash, so nothing can produce
 * it again. Copy it when you see it, or reissue.
 */

export type OrgRole = "owner" | "manager" | "analyst" | "viewer";

export const ROLES: { key: OrgRole; label: string; hint: string }[] = [
  { key: "owner", label: "Owner", hint: "Everything, including approvals, sign-off and the team" },
  { key: "manager", label: "Manager", hint: "Approvals and sign-off, and can invite below themselves" },
  { key: "analyst", label: "Analyst", hint: "Uploads, validates and configures. Cannot approve" },
  { key: "viewer", label: "Viewer", hint: "Reads only, and employee identities are masked" },
];

export const ROLE_LABEL: Record<string, string> = Object.fromEntries(
  ROLES.map((r) => [r.key, r.label]),
);

/** Ranks run widest-first, so a lower number is a wider role. */
const RANK: Record<string, number> = { owner: 0, manager: 1, analyst: 2, viewer: 3 };

/** Whether someone holding `actor` may grant `target`. Mirrors the API's rule. */
export function canGrant(actor: string | null | undefined, target: string): boolean {
  if (!actor) return false;
  const a = RANK[actor];
  const t = RANK[target];
  return a !== undefined && t !== undefined && a <= t;
}

export type Member = {
  id: string;
  user_id: string;
  email: string | null;
  role: OrgRole;
  /** Empty means every entity in the organization. */
  entity_ids: string[];
  is_you: boolean;
  joined_at: string | null;
};

export type InvitationState = "pending" | "accepted" | "revoked" | "expired";

export type Invitation = {
  id: string;
  email: string;
  role: OrgRole;
  state: InvitationState;
  entity_ids: string[];
  note: string | null;
  invited_by: string | null;
  created_at: string | null;
  expires_at: string | null;
  accepted_at: string | null;
  /** Present only on the response that issued it. Never retrievable again. */
  token?: string;
};

export type InvitationPreview = {
  organization: string;
  role: OrgRole;
  email: string;
  invited_by: string | null;
  expires_at: string | null;
  entity_names: string[];
  account_exists: boolean;
};

const base = "/api/org";

export const fetchMembers = () =>
  apiFetch(`${base}/members`).then((r) => parseEnvelopeResponse<Member[]>(r));

export const fetchInvitations = () =>
  apiFetch(`${base}/invitations`).then((r) => parseEnvelopeResponse<Invitation[]>(r));

export function createInvitation(body: {
  email: string;
  role: OrgRole;
  entity_ids: string[];
  note?: string | null;
  expiry_days?: number;
}) {
  return apiFetch(`${base}/invitations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => parseEnvelopeResponse<Invitation>(r));
}

export const resendInvitation = (id: string) =>
  apiFetch(`${base}/invitations/${id}/resend`, { method: "POST" }).then((r) =>
    parseEnvelopeResponse<Invitation>(r),
  );

export const revokeInvitation = (id: string) =>
  apiFetch(`${base}/invitations/${id}`, { method: "DELETE" }).then((r) =>
    parseEnvelopeResponse<{ revoked: boolean }>(r),
  );

export function updateMember(userId: string, body: { role?: OrgRole; entity_ids?: string[] }) {
  return apiFetch(`${base}/members/${userId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => parseEnvelopeResponse<Member>(r));
}

export const removeMember = (userId: string) =>
  apiFetch(`${base}/members/${userId}`, { method: "DELETE" }).then((r) =>
    parseEnvelopeResponse<{ removed: boolean }>(r),
  );

/** Unauthenticated — the invitee has no session yet. */
export const previewInvitation = (token: string) =>
  apiFetch(`${base}/invitations/lookup?token=${encodeURIComponent(token)}`).then((r) =>
    parseEnvelopeResponse<InvitationPreview>(r),
  );

/** Create the invited account and sign in as it. */
export async function registerFromInvitation(token: string, password: string) {
  const res = await apiFetch(`${base}/invitations/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, password }),
  });
  const tokens = await parseEnvelopeResponse<{ access_token: string; refresh_token: string }>(res);
  setTokens(tokens.access_token, tokens.refresh_token);
  return tokens;
}

/** Join as the account already signed in. */
export const acceptInvitation = (token: string) =>
  apiFetch(`${base}/invitations/accept`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  }).then((r) =>
    parseEnvelopeResponse<{ joined: boolean; organization: string; role: string }>(r),
  );

/** Where an invitation link points. */
export function invitationUrl(token: string): string {
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  return `${origin}/invite?token=${encodeURIComponent(token)}`;
}

export const STATE_TONE: Record<InvitationState, string> = {
  pending: "bg-brand-500/10 text-brand-700 ring-1 ring-brand-500/25 dark:text-brand-300",
  accepted: "bg-success-500/10 text-success-700 ring-1 ring-success-500/25 dark:text-success-300",
  revoked: "bg-ink-500/10 text-ink-600 ring-1 ring-ink-500/20 dark:text-ink-300",
  expired: "bg-warning-500/10 text-warning-800 ring-1 ring-warning-500/25 dark:text-warning-200",
};

export function formatWhen(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
