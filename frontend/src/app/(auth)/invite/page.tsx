"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { AlertTriangle, ArrowRight, Building2, Loader2, ShieldCheck } from "lucide-react";

import { AuthShell } from "@/components/auth/AuthShell";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/context/AuthContext";
import {
  ROLE_LABEL,
  acceptInvitation,
  formatWhen,
  previewInvitation,
  registerFromInvitation,
  type InvitationPreview,
} from "@/lib/team";

export default function InvitePage() {
  return (
    <Suspense fallback={<AuthShell><Waiting /></AuthShell>}>
      <InviteInner />
    </Suspense>
  );
}

function Waiting() {
  return (
    <p className="flex items-center gap-2 text-sm text-ink-500">
      <Loader2 size={15} className="animate-spin" /> Checking the invitation…
    </p>
  );
}

/**
 * Accepting an invitation.
 *
 * Two paths, chosen by whether the invited address already has an account. The
 * page never offers an email field: the address comes from the invitation, so a
 * valid link cannot be spent creating an account under some other name.
 */
function InviteInner() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token") ?? "";
  const { isAuthenticated, user, refreshUser } = useAuth();

  const [preview, setPreview] = useState<InvitationPreview | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    if (!token) {
      setFailed("This link is missing its invitation code.");
      return;
    }
    previewInvitation(token).then(
      (result) => live && setPreview(result),
      (err: Error) => live && setFailed(err.message),
    );
    return () => {
      live = false;
    };
  }, [token]);

  async function join(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (isAuthenticated) {
        await acceptInvitation(token);
      } else {
        await registerFromInvitation(token, password);
      }
      await refreshUser();
      router.push("/dashboard");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (failed) {
    return (
      <AuthShell>
        <div className="animate-fade-up">
          <span className="inline-flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.25em] text-danger-600">
            <AlertTriangle size={13} /> Invitation
          </span>
          <h1 className="mt-2 font-display text-2xl font-bold tracking-tight text-ink-900">
            This link cannot be used
          </h1>
          <p className="mt-2.5 text-sm leading-relaxed text-ink-500">{failed}</p>
          <p className="mt-2 text-sm leading-relaxed text-ink-500">
            Invitations expire, and can be revoked or already used. Ask whoever invited you
            to issue a new link.
          </p>
          <Link
            href="/login"
            className="mt-6 inline-flex items-center gap-1.5 text-sm font-medium text-brand-600 hover:underline"
          >
            Go to sign in <ArrowRight size={14} />
          </Link>
        </div>
      </AuthShell>
    );
  }

  if (!preview) {
    return (
      <AuthShell>
        <Waiting />
      </AuthShell>
    );
  }

  // Signed in as somebody else: the invitation is bound to its address, so the
  // only way forward is to sign out and come back.
  const wrongAccount =
    isAuthenticated && user?.email && user.email.toLowerCase() !== preview.email.toLowerCase();

  return (
    <AuthShell>
      <div className="animate-fade-up">
        <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-brand-600">
          You have been invited
        </p>
        <h1 className="mt-2 font-display text-3xl font-bold tracking-tight text-ink-900">
          Join {preview.organization}
        </h1>
        <p className="mt-2.5 text-sm leading-relaxed text-ink-500">
          {preview.invited_by ? `${preview.invited_by} invited ` : "You were invited as "}
          <span className="font-medium text-ink-800">{preview.email}</span>
          {preview.invited_by && " to join"} as a{" "}
          <span className="font-medium text-ink-800">
            {(ROLE_LABEL[preview.role] ?? preview.role).toLowerCase()}
          </span>
          .
        </p>

        <dl className="mt-5 space-y-2 rounded-xl border border-ink-200 bg-white/60 p-4 text-[13px]">
          <div className="flex items-start gap-2">
            <Building2 size={14} className="mt-0.5 shrink-0 text-ink-400" />
            <div>
              <dt className="font-medium text-ink-800">
                {preview.entity_names.length === 0
                  ? "Every entity in the organization"
                  : preview.entity_names.join(", ")}
              </dt>
              <dd className="text-ink-500">What you will be able to open</dd>
            </div>
          </div>
          <div className="flex items-start gap-2">
            <ShieldCheck size={14} className="mt-0.5 shrink-0 text-ink-400" />
            <div>
              <dt className="font-medium text-ink-800">
                Expires {formatWhen(preview.expires_at)}
              </dt>
              <dd className="text-ink-500">After that the link stops working</dd>
            </div>
          </div>
        </dl>

        {wrongAccount ? (
          <div className="mt-6 rounded-xl border border-warning-200 bg-warning-50/70 p-4">
            <p className="text-sm font-medium text-warning-900">
              You are signed in as {user?.email}
            </p>
            <p className="mt-1 text-[13px] text-warning-800">
              This invitation was sent to {preview.email}. Sign out and open this link again
              as that address.
            </p>
          </div>
        ) : preview.account_exists && !isAuthenticated ? (
          <div className="mt-6 rounded-xl border border-ink-200 bg-white/60 p-4">
            <p className="text-sm font-medium text-ink-800">
              {preview.email} already has an account
            </p>
            <p className="mt-1 text-[13px] text-ink-500">
              Sign in, then open this link again to accept.
            </p>
            <Link
              href="/login"
              className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-brand-600 hover:underline"
            >
              Sign in <ArrowRight size={14} />
            </Link>
          </div>
        ) : (
          <form onSubmit={join} className="mt-6 space-y-4">
            {!isAuthenticated && (
              <div>
                <Label htmlFor="invite-password">Choose a password</Label>
                <input
                  id="invite-password"
                  type="password"
                  required
                  minLength={8}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="At least 8 characters"
                  className="mt-1.5 h-10 w-full rounded-lg border border-ink-200 bg-white px-3 text-sm text-ink-900 placeholder:text-ink-400"
                />
                <p className="mt-1.5 text-[12px] text-ink-500">
                  Your account will be created as {preview.email}.
                </p>
              </div>
            )}

            {error && (
              <p className="rounded-lg border border-danger-200 bg-danger-50 px-3 py-2 text-[13px] text-danger-800">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={busy || (!isAuthenticated && password.length < 8)}
              className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-brand-600 px-4 text-sm font-semibold text-white transition hover:bg-brand-700 disabled:opacity-50"
            >
              {busy ? <Loader2 size={15} className="animate-spin" /> : null}
              {isAuthenticated ? "Accept and join" : "Create account and join"}
            </button>
          </form>
        )}
      </div>
    </AuthShell>
  );
}
