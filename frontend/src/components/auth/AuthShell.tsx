import type { ReactNode } from "react";
import Link from "next/link";
import {
  Sparkles,
  ShieldCheck,
  Zap,
  TrendingUp,
} from "lucide-react";

const stats = [
  { label: "PF · ESIC · PT · LWF · IT", icon: ShieldCheck },
  { label: "FY 2025-26 ready", icon: TrendingUp },
  { label: "<2 min to validate", icon: Zap },
];

const customers = [
  "Manufacturing",
  "BPO / KPO",
  "IT Services",
  "Retail Chains",
  "Healthcare",
  "Logistics",
  "Construction",
  "Financial Services",
];

export function AuthShell({
  brandTitle,
  brandSubtitle,
  children,
}: {
  brandTitle?: string;
  brandSubtitle?: string;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-ink-950 text-white">
      <div className="mx-auto flex min-h-screen max-w-[1400px]">
        {/* LEFT — premium hero */}
        <aside className="relative hidden overflow-hidden lg:flex lg:w-[55%] lg:flex-col lg:px-14 lg:py-14">
          {/* mesh gradient bg */}
          <div
            aria-hidden
            className="absolute inset-0"
            style={{
              background:
                "radial-gradient(ellipse 80% 60% at 18% 20%, rgba(124,58,237,0.55) 0%, transparent 55%), radial-gradient(ellipse 70% 60% at 86% 22%, rgba(59,130,246,0.45) 0%, transparent 55%), radial-gradient(ellipse 70% 60% at 50% 100%, rgba(236,72,153,0.40) 0%, transparent 55%)",
            }}
          />
          <div
            aria-hidden
            className="absolute inset-0 opacity-[0.06]"
            style={{
              backgroundImage:
                "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")",
            }}
          />

          <div className="relative z-10">
            <Link href="/dashboard" className="inline-flex items-center gap-2.5">
              <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/10 ring-1 ring-white/20 backdrop-blur">
                <Sparkles className="h-5 w-5 text-white" strokeWidth={2.25} />
              </span>
              <span className="font-display text-base font-bold tracking-tight">PayrollCheck</span>
            </Link>
          </div>

          <div className="relative z-10 mt-auto">
            <p className="mb-4 text-[10px] font-bold uppercase tracking-[0.25em] text-white/60">
              For HR &amp; Finance teams in India
            </p>
            <h2 className="font-display text-balance text-[42px] font-bold leading-[1.05] tracking-tightest text-white">
              {brandTitle ?? (
                <>
                  Audit-grade payroll
                  <br />
                  validation,{" "}
                  <span className="bg-gradient-to-r from-pink-300 via-fuchsia-300 to-amber-200 bg-clip-text text-transparent">
                    in one click.
                  </span>
                </>
              )}
            </h2>
            <p className="mt-5 max-w-md text-[15px] leading-relaxed text-white/75">
              {brandSubtitle ??
                "Validate every register against PF, ESIC, PT, LWF and Income Tax rules. Catch mismatches before they become legal liabilities."}
            </p>

            <div className="mt-8 flex flex-wrap gap-3">
              {stats.map((s) => {
                const Icon = s.icon;
                return (
                  <span
                    key={s.label}
                    className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-semibold text-white/85 backdrop-blur"
                  >
                    <Icon size={14} className="text-pink-200" />
                    {s.label}
                  </span>
                );
              })}
            </div>
          </div>

          <div className="relative z-10 mt-12 overflow-hidden">
            <p className="mb-2.5 text-[10px] font-semibold uppercase tracking-[0.22em] text-white/40">
              Built for industries
            </p>
            <div className="relative">
              <div className="flex w-max animate-marquee gap-3">
                {[...customers, ...customers].map((c, i) => (
                  <span
                    key={`${c}-${i}`}
                    className="flex-shrink-0 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs font-medium text-white/70"
                  >
                    {c}
                  </span>
                ))}
              </div>
              <div
                aria-hidden
                className="pointer-events-none absolute inset-y-0 right-0 w-32 bg-gradient-to-l from-ink-950 to-transparent"
              />
            </div>
          </div>
        </aside>

        {/* RIGHT — form area */}
        <main className="relative flex flex-1 flex-col justify-center bg-white px-5 py-12 text-ink-900 sm:px-10 lg:px-16 lg:py-14">
          <div
            aria-hidden
            className="pointer-events-none absolute right-0 top-0 h-64 w-64 rounded-full bg-brand-200/30 blur-3xl lg:hidden"
          />
          <div className="mx-auto w-full max-w-[440px]">
            <div className="mb-8 flex items-center gap-2.5 lg:hidden">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-brand-600 to-accent-600 text-white shadow-soft">
                <Sparkles size={17} strokeWidth={2.25} />
              </span>
              <span className="font-display text-base font-bold tracking-tight text-ink-900">
                PayrollCheck
              </span>
            </div>
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
