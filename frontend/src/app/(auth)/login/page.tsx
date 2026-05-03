"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { ArrowRight, Eye, EyeOff, Loader2 } from "lucide-react";

import { AuthShell } from "@/components/auth/AuthShell";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/context/AuthContext";

export default function LoginPage() {
  const router = useRouter();
  const { login, isAuthenticated } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [showPwd, setShowPwd] = useState(false);

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
    <AuthShell>
      <div className="animate-fade-up">
        <p className="text-[10px] font-bold uppercase tracking-[0.25em] text-brand-600">
          Welcome back
        </p>
        <h1 className="mt-2 font-display text-3xl font-bold tracking-tight text-ink-900">
          Sign in to your <span className="text-gradient">workspace</span>
        </h1>
        <p className="mt-2.5 text-sm leading-relaxed text-ink-500">
          Enter your work email and password. We&apos;ll match you to the right tenant and statutory
          configuration automatically.
        </p>

        <form onSubmit={onSubmit} className="mt-8 space-y-5">
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
            <div className="flex items-center justify-between">
              <Label htmlFor="password" className="text-[12px] font-semibold text-ink-800">
                Password
              </Label>
              <Link
                href="/login"
                className="text-[11px] font-semibold text-brand-600 hover:text-brand-700"
              >
                Forgot?
              </Link>
            </div>
            <div className="relative">
              <input
                id="password"
                type={showPwd ? "text" : "password"}
                autoComplete="current-password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="h-12 w-full rounded-xl border border-ink-200 bg-white px-4 pr-11 text-sm font-medium outline-none transition-all focus:border-brand-500 focus:ring-4 focus:ring-brand-500/15"
                placeholder="••••••••••"
              />
              <button
                type="button"
                onClick={() => setShowPwd((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-ink-400 transition-colors hover:text-ink-700"
                aria-label={showPwd ? "Hide password" : "Show password"}
              >
                {showPwd ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          <button
            type="submit"
            disabled={busy}
            className="group relative inline-flex h-12 w-full items-center justify-center gap-2 overflow-hidden rounded-xl bg-gradient-to-br from-brand-600 to-accent-600 text-sm font-semibold text-white shadow-[0_8px_28px_-8px_rgba(99,102,241,0.55)] transition-all hover:shadow-[0_12px_32px_-8px_rgba(99,102,241,0.7)] disabled:opacity-60"
          >
            <span
              aria-hidden
              className="absolute inset-0 bg-gradient-to-br from-white/20 to-transparent opacity-0 transition-opacity group-hover:opacity-100"
            />
            <span className="relative flex items-center gap-2">
              {busy ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Signing in…
                </>
              ) : (
                <>
                  Sign in
                  <ArrowRight
                    size={16}
                    strokeWidth={2.25}
                    className="transition-transform group-hover:translate-x-0.5"
                  />
                </>
              )}
            </span>
          </button>
        </form>

        <div className="my-7 flex items-center gap-3">
          <div className="h-px flex-1 bg-ink-200" />
          <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-400">
            or
          </span>
          <div className="h-px flex-1 bg-ink-200" />
        </div>

        <Link
          href="/dashboard"
          className="flex h-12 w-full items-center justify-center gap-2 rounded-xl border border-ink-200 bg-white text-sm font-semibold text-ink-800 transition-all hover:bg-ink-50"
        >
          Continue without signing in
          <ArrowRight
            size={15}
            className="text-ink-400 transition-transform group-hover:translate-x-0.5"
          />
        </Link>

        <p className="mt-8 text-center text-sm text-ink-500">
          Don&apos;t have an account?{" "}
          <Link
            href="/signup"
            className="font-semibold text-brand-600 hover:text-brand-700 hover:underline"
          >
            Create workspace
          </Link>
        </p>
      </div>
    </AuthShell>
  );
}
