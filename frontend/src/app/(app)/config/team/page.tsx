"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  Copy,
  Loader2,
  Mail,
  RotateCw,
  Trash2,
  UserPlus,
  Users,
} from "lucide-react";

import { Menu, MenuItem } from "@/components/cost/Menu";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import { fetchDimensions } from "@/lib/cost-analysis";
import {
  ROLES,
  ROLE_LABEL,
  STATE_TONE,
  canGrant,
  createInvitation,
  fetchInvitations,
  fetchMembers,
  formatWhen,
  invitationUrl,
  removeMember,
  resendInvitation,
  revokeInvitation,
  updateMember,
  type Invitation,
  type Member,
  type OrgRole,
} from "@/lib/team";
import { apiFetch, parseEnvelopeResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

type EntityLite = { id: string; name: string; code: string };
type Context = { role: OrgRole | null; entities: EntityLite[] };

function fetchContext() {
  return apiFetch("/api/org/context").then((r) => parseEnvelopeResponse<Context>(r));
}

/**
 * The team screen.
 *
 * Until this existed an organization could only ever have the one member that
 * signup created — a second person meant an INSERT by whoever held the database
 * password, and no record of who granted access to a month of salary data.
 */
export default function TeamPage() {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [issued, setIssued] = useState<Invitation | null>(null);

  const { data: context } = useQuery({ queryKey: ["org-context"], queryFn: fetchContext });
  const { data: members } = useQuery({ queryKey: ["org-members"], queryFn: fetchMembers });
  const { data: invitations } = useQuery({
    queryKey: ["org-invitations"],
    queryFn: fetchInvitations,
  });
  const { data: dimensions } = useQuery({ queryKey: ["dimensions"], queryFn: fetchDimensions });
  void dimensions;

  const myRole = context?.role ?? null;
  const entities = context?.entities ?? [];

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["org-members"] });
    queryClient.invalidateQueries({ queryKey: ["org-invitations"] });
  };

  const invite = useMutation({
    mutationFn: createInvitation,
    onSuccess: (result) => {
      setError(null);
      setIssued(result);
      refresh();
    },
    onError: (err: Error) => setError(err.message),
  });

  const patch = useMutation({
    mutationFn: ({ userId, body }: { userId: string; body: { role?: OrgRole; entity_ids?: string[] } }) =>
      updateMember(userId, body),
    onSuccess: () => {
      setError(null);
      refresh();
    },
    onError: (err: Error) => setError(err.message),
  });

  const drop = useMutation({
    mutationFn: removeMember,
    onSuccess: () => {
      setError(null);
      refresh();
    },
    onError: (err: Error) => setError(err.message),
  });

  const resend = useMutation({
    mutationFn: resendInvitation,
    onSuccess: (result) => {
      setError(null);
      setIssued(result);
      refresh();
    },
    onError: (err: Error) => setError(err.message),
  });

  const revoke = useMutation({
    mutationFn: revokeInvitation,
    onSuccess: () => {
      setError(null);
      refresh();
    },
    onError: (err: Error) => setError(err.message),
  });

  const pending = (invitations ?? []).filter((i) => i.state === "pending" || i.state === "expired");
  const history = (invitations ?? []).filter((i) => i.state === "accepted" || i.state === "revoked");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Team"
        description="Who can open this organization, what they can do, and which entities they can see."
      />

      {error && (
        <AlertBanner variant="error" title="That did not work">
          {error}
        </AlertBanner>
      )}

      {issued?.token && <TokenPanel invitation={issued} onDone={() => setIssued(null)} />}

      <InviteForm
        myRole={myRole}
        entities={entities}
        busy={invite.isPending}
        onInvite={(body) => invite.mutate(body)}
      />

      <Card>
        <CardContent className="py-5">
          <h3 className="flex items-center gap-2 pb-1 text-base font-semibold text-ink-900 dark:text-white">
            <Users size={16} className="text-ink-400" /> Members
          </h3>
          <p className="pb-3 text-xs text-ink-500 dark:text-ink-400">
            You cannot change your own role or remove yourself — both directions are how an
            organization ends up with nobody who can administer it.
          </p>

          <div className="divide-y divide-ink-200/70 dark:divide-ink-700/60">
            {(members ?? []).map((member) => (
              <MemberRow
                key={member.user_id}
                member={member}
                myRole={myRole}
                entities={entities}
                busy={patch.isPending || drop.isPending}
                onRole={(role) => patch.mutate({ userId: member.user_id, body: { role } })}
                onScope={(entity_ids) =>
                  patch.mutate({ userId: member.user_id, body: { entity_ids } })
                }
                onRemove={() => drop.mutate(member.user_id)}
              />
            ))}
            {!members?.length && (
              <p className="py-6 text-sm text-ink-500 dark:text-ink-400">Loading…</p>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="py-5">
          <h3 className="flex items-center gap-2 pb-1 text-base font-semibold text-ink-900 dark:text-white">
            <Mail size={16} className="text-ink-400" /> Invitations
          </h3>
          <p className="pb-3 text-xs text-ink-500 dark:text-ink-400">
            An unaccepted invitation is an outstanding key to this organization&apos;s payroll.
            They expire, and you can revoke one at any time.
          </p>

          {pending.length ? (
            <div className="divide-y divide-ink-200/70 dark:divide-ink-700/60">
              {pending.map((invitation) => (
                <div
                  key={invitation.id}
                  className="flex flex-wrap items-center justify-between gap-3 py-3"
                >
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-ink-900 dark:text-white">
                      {invitation.email}
                      <StateChip state={invitation.state} />
                      <span className="text-xs font-normal text-ink-500 dark:text-ink-400">
                        {ROLE_LABEL[invitation.role]}
                      </span>
                    </p>
                    <p className="text-xs text-ink-500 dark:text-ink-400">
                      Invited by {invitation.invited_by ?? "—"} ·{" "}
                      {invitation.state === "expired" ? "expired" : "expires"}{" "}
                      {formatWhen(invitation.expires_at)}
                      {invitation.entity_ids.length > 0 &&
                        ` · ${invitation.entity_ids.length} entit${invitation.entity_ids.length === 1 ? "y" : "ies"}`}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => resend.mutate(invitation.id)}
                      disabled={resend.isPending}
                      className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-ink-200 px-2.5 text-xs font-medium text-ink-700 transition hover:bg-ink-50 disabled:opacity-50 dark:border-ink-700 dark:text-ink-200 dark:hover:bg-ink-800"
                    >
                      <RotateCw size={12} /> New link
                    </button>
                    <button
                      type="button"
                      onClick={() => revoke.mutate(invitation.id)}
                      className="text-ink-400 transition hover:text-danger-600"
                      aria-label={`Revoke the invitation to ${invitation.email}`}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="py-4 text-sm text-ink-500 dark:text-ink-400">
              Nothing outstanding.
            </p>
          )}

          {history.length > 0 && (
            <details className="pt-4">
              <summary className="cursor-pointer text-xs font-medium text-ink-500 hover:text-ink-700 dark:text-ink-400">
                {history.length} closed invitation{history.length === 1 ? "" : "s"}
              </summary>
              <div className="divide-y divide-ink-200/70 pt-2 dark:divide-ink-700/60">
                {history.map((invitation) => (
                  <p
                    key={invitation.id}
                    className="flex flex-wrap items-center gap-2 py-2 text-xs text-ink-500 dark:text-ink-400"
                  >
                    {invitation.email} <StateChip state={invitation.state} />
                    {invitation.accepted_at && `joined ${formatWhen(invitation.accepted_at)}`}
                  </p>
                ))}
              </div>
            </details>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function StateChip({ state }: { state: Invitation["state"] }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        STATE_TONE[state],
      )}
    >
      {state}
    </span>
  );
}

/**
 * The one and only sight of a token.
 *
 * The API stores a hash, so nothing can produce this again — which is why the
 * panel says so rather than letting someone assume they can come back for it.
 */
function TokenPanel({ invitation, onDone }: { invitation: Invitation; onDone: () => void }) {
  const [copied, setCopied] = useState(false);
  const url = invitationUrl(invitation.token as string);

  return (
    <Card>
      <CardContent className="space-y-3 py-5">
        <div>
          <h3 className="text-base font-semibold text-ink-900 dark:text-white">
            Invitation link for {invitation.email}
          </h3>
          <p className="text-xs text-ink-500 dark:text-ink-400">
            Send this to them yourself. It is shown once — only a hash is stored, so this
            page cannot produce it again. Lost it? Issue a new link.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <code className="min-w-0 flex-1 overflow-x-auto rounded-lg border border-ink-200 bg-ink-50 px-3 py-2 font-mono text-xs text-ink-800 dark:border-ink-700 dark:bg-ink-900 dark:text-ink-100">
            {url}
          </code>
          <button
            type="button"
            onClick={() => {
              navigator.clipboard?.writeText(url).then(
                () => {
                  setCopied(true);
                  window.setTimeout(() => setCopied(false), 2000);
                },
                () => setCopied(false),
              );
            }}
            className="inline-flex h-9 items-center gap-2 rounded-lg bg-brand-600 px-3 text-sm font-medium text-white transition hover:bg-brand-700"
          >
            {copied ? <Check size={14} /> : <Copy size={14} />}
            {copied ? "Copied" : "Copy"}
          </button>
          <button
            type="button"
            onClick={onDone}
            className="inline-flex h-9 items-center rounded-lg border border-ink-200 px-3 text-sm font-medium text-ink-700 transition hover:bg-ink-50 dark:border-ink-700 dark:text-ink-200 dark:hover:bg-ink-800"
          >
            Done
          </button>
        </div>
      </CardContent>
    </Card>
  );
}

function InviteForm({
  myRole,
  entities,
  busy,
  onInvite,
}: {
  myRole: OrgRole | null;
  entities: EntityLite[];
  busy: boolean;
  onInvite: (body: { email: string; role: OrgRole; entity_ids: string[]; note?: string | null }) => void;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<OrgRole>("analyst");
  const [scope, setScope] = useState<string[]>([]);

  const grantable = ROLES.filter((r) => canGrant(myRole, r.key));

  return (
    <Card>
      <CardContent className="py-5">
        <h3 className="flex items-center gap-2 pb-1 text-base font-semibold text-ink-900 dark:text-white">
          <UserPlus size={16} className="text-ink-400" /> Invite someone
        </h3>
        <p className="pb-4 text-xs text-ink-500 dark:text-ink-400">
          You can only invite at your own level or below. Leave the entities empty to give
          access to all of them.
        </p>

        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[15rem] flex-1">
            <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wide text-ink-400">
              Email
            </span>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="name@company.in"
              className="h-9 w-full rounded-lg border border-ink-200 bg-white px-3 text-sm text-ink-900 placeholder:text-ink-400 dark:border-ink-700 dark:bg-ink-900 dark:text-white"
            />
          </div>

          <Menu
            label="Role"
            summary={ROLE_LABEL[role] ?? role}
            width="w-80"
          >
            {(close) => (
              <>
                {grantable.map((option) => (
                  <MenuItem
                    key={option.key}
                    selected={option.key === role}
                    hint={option.hint}
                    onClick={() => {
                      setRole(option.key);
                      close();
                    }}
                  >
                    {option.label}
                  </MenuItem>
                ))}
              </>
            )}
          </Menu>

          <Menu
            label="Entities"
            summary={scope.length === 0 ? "All entities" : `${scope.length} selected`}
            count={scope.length || undefined}
            width="w-72"
          >
            {() => (
              <>
                <MenuItem selected={scope.length === 0} onClick={() => setScope([])}>
                  All entities
                </MenuItem>
                {entities.map((entity) => (
                  <MenuItem
                    key={entity.id}
                    selected={scope.includes(entity.id)}
                    onClick={() =>
                      setScope((current) =>
                        current.includes(entity.id)
                          ? current.filter((id) => id !== entity.id)
                          : [...current, entity.id],
                      )
                    }
                  >
                    {entity.name}
                  </MenuItem>
                ))}
              </>
            )}
          </Menu>

          <button
            type="button"
            disabled={!email.trim() || busy}
            onClick={() => onInvite({ email: email.trim(), role, entity_ids: scope })}
            className="inline-flex h-9 items-center gap-2 rounded-lg bg-brand-600 px-3 text-sm font-medium text-white transition hover:bg-brand-700 disabled:opacity-50"
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <UserPlus size={14} />}
            Create invitation
          </button>
        </div>
      </CardContent>
    </Card>
  );
}

function MemberRow({
  member,
  myRole,
  entities,
  busy,
  onRole,
  onScope,
  onRemove,
}: {
  member: Member;
  myRole: OrgRole | null;
  entities: EntityLite[];
  busy: boolean;
  onRole: (role: OrgRole) => void;
  onScope: (entityIds: string[]) => void;
  onRemove: () => void;
}) {
  // You cannot act on yourself, nor on anyone whose role is wider than yours.
  const mayManage = !member.is_you && canGrant(myRole, member.role);
  const grantable = ROLES.filter((r) => canGrant(myRole, r.key));

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 py-3">
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-ink-900 dark:text-white">
          {member.email}
          {member.is_you && (
            <span className="rounded-full bg-ink-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-600 dark:text-ink-300">
              You
            </span>
          )}
        </p>
        <p className="text-xs text-ink-500 dark:text-ink-400">
          {member.entity_ids.length === 0
            ? "Every entity"
            : `${member.entity_ids.length} of ${entities.length} entities`}
          {member.joined_at && ` · joined ${formatWhen(member.joined_at)}`}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {mayManage ? (
          <>
            <Menu label="" summary={ROLE_LABEL[member.role] ?? member.role} width="w-80" align="right">
              {(close) => (
                <>
                  {grantable.map((option) => (
                    <MenuItem
                      key={option.key}
                      selected={option.key === member.role}
                      hint={option.hint}
                      onClick={() => {
                        if (option.key !== member.role) onRole(option.key);
                        close();
                      }}
                    >
                      {option.label}
                    </MenuItem>
                  ))}
                </>
              )}
            </Menu>

            <Menu
              label=""
              summary={member.entity_ids.length === 0 ? "All entities" : `${member.entity_ids.length} entities`}
              width="w-72"
              align="right"
            >
              {() => (
                <>
                  <MenuItem
                    selected={member.entity_ids.length === 0}
                    onClick={() => onScope([])}
                  >
                    All entities
                  </MenuItem>
                  {entities.map((entity) => (
                    <MenuItem
                      key={entity.id}
                      selected={member.entity_ids.includes(entity.id)}
                      onClick={() =>
                        onScope(
                          member.entity_ids.includes(entity.id)
                            ? member.entity_ids.filter((id) => id !== entity.id)
                            : [...member.entity_ids, entity.id],
                        )
                      }
                    >
                      {entity.name}
                    </MenuItem>
                  ))}
                </>
              )}
            </Menu>

            <button
              type="button"
              onClick={onRemove}
              disabled={busy}
              className="text-ink-400 transition hover:text-danger-600 disabled:opacity-50"
              aria-label={`Remove ${member.email}`}
            >
              <Trash2 size={14} />
            </button>
          </>
        ) : (
          <span className="text-sm text-ink-500 dark:text-ink-400">
            {ROLE_LABEL[member.role] ?? member.role}
          </span>
        )}
      </div>
    </div>
  );
}
