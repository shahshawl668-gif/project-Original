"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/context/AuthContext";
import { apiFetch, clearTokens, getSessionPortal, parseEnvelopeResponse, setTokens } from "@/lib/api";
import { date, plural } from "@/lib/format";

type MfaStatus = { enabled: boolean; enabled_at: string | null; recovery_codes_left: number; required: boolean };
type Setup = { secret: string; otpauth_uri: string };

const field = "mt-1 block h-10 w-full rounded-lg border border-ink-200 bg-white px-3 text-[13px] text-ink-900 outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20";

async function post<T>(path: string, body: unknown): Promise<T> {
  return parseEnvelopeResponse<T>(await apiFetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), cache: "no-store",
  }));
}

/**
 * Your own sign-in: two-step sign-in, recovery codes, and signing out everywhere.
 *
 * Reachable from a client or a platform session; a support session is inside
 * someone else's workspace and changes nothing here. The secret and the
 * recovery codes are shown once and never fetched again: the server keeps the
 * secret sealed and the codes only as digests.
 */
export default function AccountSecurityPage() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const [status, setStatus] = useState<MfaStatus | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [setup, setSetup] = useState<Setup | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const portal = getSessionPortal();
  const home = portal === "platform" ? "/platform" : "/dashboard";

  const load = useCallback(async () => {
    try {
      setStatus(await parseEnvelopeResponse<MfaStatus>(await apiFetch("/api/auth/mfa", { cache: "no-store" })));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load your sign-in settings.");
    }
  }, []);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
    if (user) void load();
  }, [user, loading, router, load]);

  async function run(fn: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That did not work. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const begin = (e: FormEvent) => { e.preventDefault(); void run(async () => {
    setSetup(await post<Setup>("/api/auth/mfa/setup", { password }));
    setPassword("");
  }); };

  const confirm = (e: FormEvent) => { e.preventDefault(); void run(async () => {
    const done = await post<{ recovery_codes: string[]; access_token: string; refresh_token: string }>("/api/auth/mfa/enable", { code });
    // Turning it on ends every other session; this device carries on with the pair it was just given.
    setTokens(done.access_token, done.refresh_token);
    setCodes(done.recovery_codes);
    setSetup(null);
    setCode("");
    await load();
  }); };

  const turnOff = (e: FormEvent) => { e.preventDefault(); void run(async () => {
    await post("/api/auth/mfa/disable", { password, code });
    setPassword(""); setCode("");
    await load();
  }); };

  const newCodes = () => void run(async () => {
    setCodes((await post<{ recovery_codes: string[] }>("/api/auth/mfa/recovery-codes", { password, code })).recovery_codes);
    setPassword(""); setCode("");
    await load();
  });

  const everywhere = () => void run(async () => {
    await post("/api/auth/sessions/revoke-all", {});
    clearTokens();
    await logout();
    router.replace(portal === "platform" ? "/platform/login" : "/login");
  });

  if (loading || !user) return <main className="p-8 text-sm text-ink-600">Checking your session…</main>;
  if (portal === "support") {
    return <main className="mx-auto max-w-lg p-8 text-sm text-ink-700">A support session works inside a client&apos;s workspace. Change your own sign-in from your platform session.</main>;
  }

  return (
    <main className="mx-auto max-w-2xl space-y-6 p-6 text-ink-900">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="flex items-center gap-2 text-xl font-semibold"><ShieldCheck size={20} className="text-brand-600" aria-hidden /> Sign-in and security</h1>
        {status?.required && !status.enabled ? null : <Link href={home} className="text-[13px] font-medium text-brand-700 underline">Back</Link>}
      </header>
      <p className="text-[13px] text-ink-600">Signed in as <b>{user.email}</b>.</p>

      {error ? <p role="alert" className="rounded-lg border border-danger-200 bg-danger-50 p-3 text-[13px] text-danger-700">{error}</p> : null}

      {status?.required && !status.enabled ? (
        <p role="status" className="rounded-lg border border-warning-200 bg-warning-50 p-3 text-[13px] text-warning-800">
          Your organisation requires two-step sign-in for platform staff. Set it up below to continue.
        </p>
      ) : null}

      <section aria-labelledby="mfa-heading" className="rounded-xl border border-ink-200 bg-white p-5 shadow-soft">
        <h2 id="mfa-heading" className="text-[15px] font-semibold">Two-step sign-in</h2>
        <p className="mt-1 text-[13px] text-ink-600">
          After your password, a six-digit code from an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password and others).
          Someone who learns your password still cannot sign in without your phone.
        </p>

        {codes ? (
          <div className="mt-4 rounded-lg border border-brand-200 bg-brand-50 p-4">
            <p className="text-[13px] font-semibold">Your recovery codes — shown once</p>
            <p className="mt-1 text-xs text-ink-700">Each works once, in place of a code, if you lose your phone. Keep them somewhere safe and offline. They will not be shown again.</p>
            <ul className="mt-3 grid grid-cols-2 gap-1 font-mono text-[13px]">{codes.map((c) => <li key={c}>{c}</li>)}</ul>
            <Button size="sm" className="mt-3" onClick={() => setCodes(null)}>I have saved them</Button>
          </div>
        ) : null}

        {status === null ? <p className="mt-3 text-xs text-ink-500">Loading…</p> : status.enabled ? (
          <div className="mt-4 space-y-4">
            <p className="text-[13px] text-success-800">On since {date(status.enabled_at)} · {plural(status.recovery_codes_left, "recovery code")} left.</p>
            <form onSubmit={turnOff} className="space-y-3">
              <p className="text-xs text-ink-600">To turn it off or replace your recovery codes, confirm your password and a current code.</p>
              <label className="block text-xs font-medium text-ink-700">Password
                <input type="password" autoComplete="current-password" className={field} value={password} onChange={(e) => setPassword(e.target.value)} required />
              </label>
              <label className="block text-xs font-medium text-ink-700">Code or recovery code
                <input autoComplete="one-time-code" className={field} value={code} onChange={(e) => setCode(e.target.value)} required maxLength={32} />
              </label>
              <div className="flex flex-wrap gap-2">
                <Button type="button" size="sm" variant="outline" disabled={busy || !password || !code} onClick={newCodes}>New recovery codes</Button>
                <Button type="submit" size="sm" variant="destructive-outline" disabled={busy || !password || !code}>Turn off</Button>
              </div>
            </form>
          </div>
        ) : setup ? (
          <form onSubmit={confirm} className="mt-4 space-y-3">
            <ol className="list-decimal space-y-2 pl-5 text-[13px] text-ink-700">
              <li>In your authenticator app, add an account and choose to enter a key. On a phone you can instead <a className="font-medium text-brand-700 underline" href={setup.otpauth_uri}>open it in the app</a>.</li>
              <li>Key: <code className="select-all break-all rounded bg-ink-50 px-1.5 py-0.5 font-mono text-[13px]">{setup.secret.match(/.{1,4}/g)?.join(" ")}</code> (time-based, six digits)</li>
              <li>Enter the code the app shows.</li>
            </ol>
            <label className="block text-xs font-medium text-ink-700">Code
              <input autoComplete="one-time-code" inputMode="numeric" className={field} value={code} onChange={(e) => setCode(e.target.value)} required maxLength={8} />
            </label>
            <div className="flex gap-2">
              <Button type="submit" size="sm" disabled={busy || code.trim().length < 6}>Turn on</Button>
              <Button type="button" size="sm" variant="ghost" onClick={() => { setSetup(null); setCode(""); }}>Cancel</Button>
            </div>
          </form>
        ) : (
          <form onSubmit={begin} className="mt-4 space-y-3">
            <label className="block text-xs font-medium text-ink-700">Confirm your password to begin
              <input type="password" autoComplete="current-password" className={field} value={password} onChange={(e) => setPassword(e.target.value)} required />
            </label>
            <Button type="submit" size="sm" disabled={busy || !password}>Set up two-step sign-in</Button>
          </form>
        )}
      </section>

      <section aria-labelledby="sessions-heading" className="rounded-xl border border-ink-200 bg-white p-5 shadow-soft">
        <h2 id="sessions-heading" className="text-[15px] font-semibold">Sign out everywhere</h2>
        <p className="mt-1 text-[13px] text-ink-600">
          Ends every session on every device, this one included — for a lost laptop or a password you think someone else knows.
          It stops further access; it cannot recall a file already downloaded to a device.
        </p>
        <Button size="sm" variant="destructive-outline" className="mt-3" disabled={busy} onClick={everywhere}>Sign out everywhere</Button>
      </section>
    </main>
  );
}
