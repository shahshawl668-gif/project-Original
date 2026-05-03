"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { ArrowRight, CheckCircle2, Loader2 } from "lucide-react";

import { AuthShell } from "@/components/auth/AuthShell";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/context/AuthContext";

const benefits = [
  "Validate PF, ESIC, PT, LWF in seconds",
  "Old vs new regime tax projection",
  "Excel audit trail for every register",
  "Tenant-isolated, role-based access",
];

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
    <AuthShell>
      <div className="animate-fade-up">
        <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-brand-600">
          Create workspace
        </p>
        <h1 className="mt-2 font-display text-3xl font-bold tracking-tight text-ink-900">
          Get started in <span className="text-gradient">90 seconds</span>
        </h1>
        <p className="mt-2.5 text-sm leading-relaxed text-ink-500">
          The first user in an empty workspace becomes the admin. No credit card. No commitment.
        </p>

        <ul className="mt-6 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {benefits.map((b) => (
            <li key={b} className="flex items-start gap-2 text-[12px] text-ink-700">
              <CheckCircle2 size={14} className="mt-0.5 flex-shrink-0 text-success-500" />
              {b}
            </li>
          ))}
        </ul>

        <form onSubmit={onSubmit} className="mt-7 space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="company" className="text-[12px] font-semibold text-ink-800">
              Company / workspace
              <span className="ml-1 text-ink-400">(optional)</span>
            </Label>
            <input
              id="company"
              type="text"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              className="h-12 w-full rounded-xl border border-ink-200 bg-white px-4 text-sm font-medium outline-none transition-all placeholder:text-ink-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-500/15"
              placeholder="Acme India Pvt Ltd"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="email" className="text-[12px] font-semibold text-ink-800">
              Work email
            </Label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="h-12 w-full rounded-xl border border-ink-200 bg-white px-4 text-sm font-medium outline-none transition-all placeholder:text-ink-400 focus:border-brand-500 focus:ring-4 focus:ring-brand-500/15"
              placeholder="you@company.com"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password" className="text-[12px] font-semibold text-ink-800">
              Password
              <span className="ml-1 text-ink-400">(min 8 characters)</span>
            </Label>
            <input
              id="password"
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="h-12 w-full rounded-xl border border-ink-200 bg-white px-4 text-sm font-medium outline-none transition-all focus:border-brand-500 focus:ring-4 focus:ring-brand-500/15"
              placeholder="••••••••••"
            />
          </div>

          <button
            type="submit"
            disabled={busy}
            className="group relative mt-2 inline-flex h-12 w-full items-center justify-center gap-2 overflow-hidden rounded-xl bg-gradient-to-br from-brand-600 to-accent-600 text-sm font-semibold text-white shadow-[0_8px_28px_-8px_rgba(99,102,241,0.55)] transition-all hover:shadow-[0_12px_32px_-8px_rgba(99,102,241,0.7)] disabled:opacity-60"
          >
            <span className="relative flex items-center gap-2">
              {busy ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Creating workspace…
                </>
              ) : (
                <>
                  Create my workspace
                  <ArrowRight
                    size={16}
                    strokeWidth={2.25}
                    className="transition-transform group-hover:translate-x-0.5"
                  />
                </>
              )}
            </span>
          </button>

          <p className="text-center text-[11px] leading-relaxed text-ink-400">
            By continuing you agree to use PayrollCheck in line with your organisation&apos;s
            policies.
          </p>
        </form>

        <p className="mt-7 text-center text-sm text-ink-500">
          Already on PayrollCheck?{" "}
          <Link
            href="/login"
            className="font-semibold text-brand-600 hover:text-brand-700 hover:underline"
          >
            Sign in
          </Link>
        </p>
      </div>
    </AuthShell>
  );
}
