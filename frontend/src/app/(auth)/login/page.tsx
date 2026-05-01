"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { Loader2 } from "lucide-react";

import { AuthShell } from "@/components/auth/AuthShell";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/context/AuthContext";

export default function LoginPage() {
  const router = useRouter();
  const { login, isAuthenticated } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (isAuthenticated) router.replace("/dashboard");
  }, [isAuthenticated, router]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await login(email, password);
      router.push("/dashboard");
    } catch {
      /* AuthContext shows toast */
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell
      brandTitle="Sign in — enterprise-grade payroll validation"
      brandSubtitle="Authenticate to bind this browser session to your tenant, or continue as guest when the API allows anonymous access."
    >
      <div className="rounded-2xl border border-slate-200/90 bg-white p-8 shadow-card ring-1 ring-slate-900/[0.04] sm:p-9">
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">Welcome back</h1>
        <p className="mt-2 text-sm leading-relaxed text-slate-600">
          Use your PayrollCheck credentials. Optional sign-in when the backend runs in anonymous tenant mode.
        </p>
        <form onSubmit={onSubmit} className="mt-8 space-y-5">
          <div className="space-y-2">
            <Label htmlFor="email">Work email</Label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="h-11 w-full rounded-xl border border-slate-200 bg-slate-50/50 px-3.5 text-sm font-medium outline-none ring-brand-500/20 transition-colors placeholder:text-slate-400 focus:border-brand-400 focus:bg-white focus:ring-[3px]"
              placeholder="you@company.com"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="h-11 w-full rounded-xl border border-slate-200 bg-slate-50/50 px-3.5 text-sm font-medium outline-none ring-brand-500/20 transition-colors focus:border-brand-400 focus:bg-white focus:ring-[3px]"
            />
          </div>
          <Button type="submit" disabled={busy} className="h-11 w-full rounded-xl text-sm font-semibold shadow-soft">
            {busy ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                Signing in…
              </>
            ) : (
              "Sign in"
            )}
          </Button>
        </form>
        <p className="mt-8 text-center text-sm text-slate-600">
          No account?{" "}
          <Link href="/signup" className="font-semibold text-brand-700 hover:text-brand-800 hover:underline">
            Create one
          </Link>
        </p>
        <p className="mt-4 text-center">
          <Link
            href="/dashboard"
            className="text-xs font-medium text-slate-500 transition-colors hover:text-slate-800"
          >
            Continue without signing in →
          </Link>
        </p>
      </div>
      <p className="mt-8 text-center text-2xs font-medium uppercase tracking-widest text-slate-400 lg:text-left">
        Secured session · Tenant-scoped API
      </p>
    </AuthShell>
  );
}
