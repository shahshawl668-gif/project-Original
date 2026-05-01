"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { Loader2 } from "lucide-react";

import { AuthShell } from "@/components/auth/AuthShell";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/context/AuthContext";

export default function SignupPage() {
  const router = useRouter();
  const { signup, isAuthenticated } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [company, setCompany] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (isAuthenticated) router.replace("/dashboard");
  }, [isAuthenticated, router]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await signup(email, password, company || null);
      router.push("/dashboard");
    } catch {
      /* AuthContext shows toast */
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell
      brandTitle="Create your workspace in one step"
      brandSubtitle="The first user in an empty database receives admin privileges so you can onboard your team and statutory settings without extra setup."
    >
      <div className="rounded-2xl border border-slate-200/90 bg-white p-8 shadow-card ring-1 ring-slate-900/[0.04] sm:p-9">
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">Create account</h1>
        <p className="mt-2 text-sm leading-relaxed text-slate-600">
          Use a work email you control — we tie validations, uploads, and config to your tenant.
        </p>
        <form onSubmit={onSubmit} className="mt-8 space-y-5">
          <div className="space-y-2">
            <Label htmlFor="company">Company / workspace (optional)</Label>
            <input
              id="company"
              type="text"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              className="h-11 w-full rounded-xl border border-slate-200 bg-slate-50/50 px-3.5 text-sm font-medium outline-none ring-brand-500/20 transition-colors placeholder:text-slate-400 focus:border-brand-400 focus:bg-white focus:ring-[3px]"
              placeholder="e.g. Acme India Pvt Ltd"
            />
          </div>
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
            <Label htmlFor="password">Password (min 8 characters)</Label>
            <input
              id="password"
              type="password"
              autoComplete="new-password"
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
                Creating…
              </>
            ) : (
              "Create account"
            )}
          </Button>
        </form>
        <p className="mt-8 text-center text-sm text-slate-600">
          Already registered?{" "}
          <Link href="/login" className="font-semibold text-brand-700 hover:text-brand-800 hover:underline">
            Sign in
          </Link>
        </p>
      </div>
      <p className="mt-8 text-center text-2xs font-medium uppercase tracking-widest text-slate-400 lg:text-left">
        By continuing you agree to use this product in line with your organization&apos;s policies.
      </p>
    </AuthShell>
  );
}
