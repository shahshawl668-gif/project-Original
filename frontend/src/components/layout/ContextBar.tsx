"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { CalendarRange, Check, ChevronDown, FlaskConical, Hash, Loader2 } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { studioReleaseApi } from "@/lib/studio";
import { validationApi } from "@/lib/validation";
import { normalisePeriod, periodLabel, useWorkingPeriod } from "@/lib/workspace";
import { cn } from "@/lib/utils";

/** Routes that are about one month, where the period and run are shown. */
const MONTH_ROUTES = [/^\/control-centre/, /^\/payroll\/(upload|validation|results|issues|attendance)/, /^\/reconciliation/];

function lastMonths(n: number): string[] {
  const out: string[] = [];
  const d = new Date();
  for (let i = 0; i < n; i++) {
    const x = new Date(d.getFullYear(), d.getMonth() - i, 1);
    out.push(`${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}`);
  }
  return out;
}

/**
 * Period, run and (in Studio) environment, beside the company switcher. Each
 * is shown only where it applies, and each says where it came from: a period
 * nobody chose is labelled as the latest, not presented as a decision.
 */
export function ContextBar() {
  const pathname = usePathname();
  const { entity, activeRole } = useEntity();
  const monthScoped = MONTH_ROUTES.some((re) => re.test(pathname));
  const inStudio = pathname === "/studio" || pathname.startsWith("/studio/");
  return (
    <div className="flex items-center gap-1.5">
      {monthScoped && entity ? <PeriodPicker /> : null}
      {monthScoped && entity ? <RunChip /> : null}
      {inStudio && entity && activeRole !== "viewer" ? <EnvironmentChip /> : null}
    </div>
  );
}

function PeriodPicker() {
  const { entity } = useEntity();
  const { period, source, setPeriod, loading } = useWorkingPeriod();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const runs = useQuery({
    queryKey: ["run-periods", entity?.id],
    queryFn: () => validationApi.runs({ limit: 200 }),
    enabled: open && !!entity,
    staleTime: 60_000,
  });
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  const options = useMemo(() => {
    const withRuns = new Map<string, number>();
    for (const r of runs.data ?? []) {
      const p = normalisePeriod(r.period_month);
      if (p) withRuns.set(p, (withRuns.get(p) ?? 0) + 1);
    }
    const all = new Set(lastMonths(12).concat(Array.from(withRuns.keys())));
    return Array.from(all)
      .sort()
      .reverse()
      .map((p) => ({ p, runs: withRuns.get(p) ?? 0 }));
  }, [runs.data]);

  if (loading || !period) return <span className="hidden h-8 w-24 animate-pulse-soft rounded-lg bg-ink-100 md:inline-block" aria-hidden />;
  return (
    <div className="relative hidden md:block" ref={box}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Period: ${periodLabel(period)}${source === "chosen" ? "" : " (latest)"}. Change period`}
        className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-ink-200 bg-white px-2.5 text-[13px] font-medium text-ink-800 shadow-soft transition-colors hover:border-ink-300 hover:bg-ink-50"
      >
        <CalendarRange size={14} className="text-ink-400" aria-hidden />
        <span className="num">{periodLabel(period)}</span>
        {source !== "chosen" ? <span className="text-xs font-normal text-ink-400">latest</span> : null}
        <ChevronDown size={13} className="text-ink-400" aria-hidden />
      </button>
      {open ? (
        <div role="listbox" aria-label="Period" className="absolute right-0 z-50 mt-1.5 max-h-80 w-60 animate-fade-up overflow-y-auto rounded-xl border border-ink-200 bg-white p-1 shadow-elevated">
          <p className="px-2.5 pb-1 pt-1.5 text-xs text-ink-500">Working period for {entity?.name}</p>
          {runs.isLoading ? (
            <p className="flex items-center gap-2 px-2.5 py-2 text-xs text-ink-500"><Loader2 size={12} className="animate-spin" aria-hidden /> Loading months…</p>
          ) : null}
          {options.map(({ p, runs: n }) => (
            <button
              key={p}
              type="button"
              role="option"
              aria-selected={p === period}
              onClick={() => {
                setPeriod(p);
                setOpen(false);
              }}
              className={cn(
                "flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13px]",
                p === period ? "bg-brand-50 text-brand-900" : "text-ink-700 hover:bg-ink-50",
              )}
            >
              <span className="num flex-1">{periodLabel(p)}</span>
              <span className="text-xs text-ink-400">{n ? `${n} run${n > 1 ? "s" : ""}` : "no runs"}</span>
              {p === period ? <Check size={13} className="text-brand-700" aria-hidden /> : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function RunChip() {
  const { entity } = useEntity();
  const { period } = useWorkingPeriod();
  const status = useQuery({
    queryKey: ["period-status", entity?.id, period],
    queryFn: () => validationApi.periodStatus(`${period}-01`),
    enabled: !!entity && !!period,
    staleTime: 30_000,
    retry: false,
    placeholderData: (prev) => prev,
  });
  const s = status.data;
  if (!s) return null;
  if (s.active_job) {
    return (
      <Link
        href={`/payroll/validation?job=${s.active_job.id}`}
        className="hidden h-8 items-center gap-1.5 rounded-lg border border-brand-200 bg-brand-50 px-2.5 text-[13px] font-medium text-brand-800 lg:inline-flex"
      >
        <Loader2 size={13} className="animate-spin" aria-hidden />
        Validating {s.active_job.percent ? `${Math.round(s.active_job.percent)}%` : "…"}
      </Link>
    );
  }
  if (!s.current_run) {
    return <span className="hidden h-8 items-center rounded-lg px-2 text-xs text-ink-500 lg:inline-flex">No run this month</span>;
  }
  const stale = s.freshness?.revalidation_required;
  return (
    <Link
      href={`/payroll/results?run=${s.current_run.id}`}
      title={stale ? "Inputs changed since this run — revalidation required" : "Current run for this period"}
      className={cn(
        "hidden h-8 items-center gap-1 rounded-lg border px-2.5 text-[13px] font-medium shadow-soft transition-colors lg:inline-flex",
        stale ? "border-warning-200 bg-warning-50 text-warning-900 hover:bg-warning-100" : "border-ink-200 bg-white text-ink-800 hover:bg-ink-50",
      )}
    >
      <Hash size={13} className="text-ink-400" aria-hidden />
      <span className="num">Run {s.current_run.run_number}</span>
      <span className="text-xs font-normal text-ink-500">{stale ? "· out of date" : "· current"}</span>
    </Link>
  );
}

const ENV_TONE: Record<string, string> = {
  production: "border-success-200 bg-success-50 text-success-800",
  test: "border-warning-200 bg-warning-50 text-warning-900",
  development: "border-ink-200 bg-ink-50 text-ink-700",
};

function EnvironmentChip() {
  const { entity } = useEntity();
  const env = useQuery({
    queryKey: ["studio-env", entity?.id],
    queryFn: studioReleaseApi.environment,
    enabled: !!entity,
    staleTime: 60_000,
    retry: false,
  });
  const name = env.data?.environment;
  if (!name) return null;
  return (
    <Link
      href="/studio/releases"
      title="This company's Studio environment. Changes reach production only through an approved release."
      className={cn("hidden h-8 items-center gap-1.5 rounded-lg border px-2.5 text-[13px] font-medium capitalize md:inline-flex", ENV_TONE[name] ?? ENV_TONE.development)}
    >
      <FlaskConical size={13} aria-hidden />
      {name}
    </Link>
  );
}
