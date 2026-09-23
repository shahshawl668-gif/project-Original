"use client";

/**
 * Companies — the landing page for a group.
 *
 * What used to be here was a single-company dashboard: one hero, one set of
 * charts, describing whichever employer you happened to have selected. A group
 * running six companies had to switch entity and re-read it six times to find
 * out which one needed attention, which is how a month gets missed.
 *
 * This asks the first question instead: of everything you are responsible for,
 * what is behind? Each company carries its own state, the list is ordered by
 * trouble rather than by name, and opening one selects it and takes you into
 * the work.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Banknote,
  Building2,
  CalendarDays,
  CheckCircle2,
  IndianRupee,
  Inbox,
  Loader2,
  ShieldCheck,
  UploadCloud,
  Users,
} from "lucide-react";

import { apiJson } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useEntity } from "@/context/EntityContext";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { SectionHeader } from "@/components/ui/section-header";
import { Skeleton } from "@/components/ui/skeleton";
import { SlowRequestNotice } from "@/components/ui/slow-request-notice";

type CompanyRow = {
  id: string;
  name: string;
  code: string;
  primary_state: string | null;
  last_register_period: string | null;
  employee_count: number;
  open_findings: number;
  critical_findings: number;
  exposure: number;
  signoff_state: string | null;
};

type Portfolio = {
  entities: CompanyRow[];
  totals: {
    entities?: number;
    employees?: number;
    open_findings?: number;
    critical_findings?: number;
    exposure?: number;
    awaiting_register?: number;
  };
};

const inr = (value: number) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(value || 0);

const monthLabel = (iso: string | null) =>
  iso
    ? new Date(`${iso.length === 7 ? `${iso}-01` : iso}`).toLocaleDateString("en-IN", {
        month: "short",
        year: "numeric",
      })
    : null;

/** One number with its name. Deliberately plain — the cards carry the detail. */
function Total({
  icon: Icon,
  label,
  value,
  tone = "neutral",
}: {
  icon: typeof Users;
  label: string;
  value: string;
  tone?: "neutral" | "warn" | "good";
}) {
  const toneClass =
    tone === "warn"
      ? "text-danger-700"
      : tone === "good"
        ? "text-success-700"
        : "text-ink-900";
  return (
    <div className="flex items-center gap-3 rounded-xl border border-ink-200/70 bg-white px-4 py-3">
      <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
        <Icon size={16} strokeWidth={2} aria-hidden />
      </span>
      <span className="min-w-0">
        <span className={`block truncate text-lg font-bold leading-tight ${toneClass}`}>
          {value}
        </span>
        <span className="block truncate text-[11px] font-medium text-ink-500">{label}</span>
      </span>
    </div>
  );
}

/** The state of one company's latest month, said in words rather than a colour. */
function StatusLine({ row }: { row: CompanyRow }) {
  if (row.last_register_period === null) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md bg-ink-100 px-2 py-1 text-[11px] font-semibold text-ink-600">
        <Inbox size={12} aria-hidden /> No register yet
      </span>
    );
  }
  if (row.critical_findings > 0) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md bg-danger-50 px-2 py-1 text-[11px] font-semibold text-danger-700">
        <AlertTriangle size={12} aria-hidden />
        {row.critical_findings} critical
      </span>
    );
  }
  if (row.open_findings > 0) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md bg-warning-50 px-2 py-1 text-[11px] font-semibold text-warning-700">
        <AlertTriangle size={12} aria-hidden />
        {row.open_findings} open
      </span>
    );
  }
  if (row.signoff_state === "signed") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md bg-success-50 px-2 py-1 text-[11px] font-semibold text-success-700">
        <ShieldCheck size={12} aria-hidden /> Signed off
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md bg-success-50 px-2 py-1 text-[11px] font-semibold text-success-700">
      <CheckCircle2 size={12} aria-hidden /> Clear
    </span>
  );
}

function CompanyCard({ row }: { row: CompanyRow }) {
  const { entity, switchEntity } = useEntity();
  const router = useRouter();
  const [opening, setOpening] = useState(false);
  const isActive = entity?.id === row.id;
  const period = monthLabel(row.last_register_period);

  async function open() {
    setOpening(true);
    try {
      if (!isActive) await switchEntity(row.id);
      router.push(row.last_register_period ? "/payroll/results" : "/payroll/upload");
    } finally {
      setOpening(false);
    }
  }

  return (
    <Card
      className={`flex flex-col gap-4 p-5 transition-shadow hover:shadow-card ${
        isActive ? "ring-2 ring-brand-500" : ""
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-[15px] font-bold leading-tight text-ink-900">{row.name}</p>
          <p className="mt-0.5 truncate text-[11px] font-medium text-ink-500">
            {row.code}
            {row.primary_state ? ` · ${row.primary_state}` : ""}
          </p>
        </div>
        <StatusLine row={row} />
      </div>

      <dl className="grid grid-cols-3 gap-3 border-y border-ink-100 py-3">
        <div>
          <dt className="text-[10.5px] font-medium uppercase tracking-wide text-ink-500">Period</dt>
          <dd className="mt-0.5 truncate text-[13px] font-semibold text-ink-900">
            {period ?? "—"}
          </dd>
        </div>
        <div>
          <dt className="text-[10.5px] font-medium uppercase tracking-wide text-ink-500">People</dt>
          <dd className="mt-0.5 text-[13px] font-semibold text-ink-900">
            {row.employee_count || "—"}
          </dd>
        </div>
        <div>
          <dt className="text-[10.5px] font-medium uppercase tracking-wide text-ink-500">
            Exposure
          </dt>
          <dd
            className={`mt-0.5 truncate text-[13px] font-semibold ${
              row.exposure > 0 ? "text-danger-700" : "text-ink-900"
            }`}
          >
            {row.exposure > 0 ? inr(row.exposure) : "—"}
          </dd>
        </div>
      </dl>

      <div className="flex items-center justify-between gap-3">
        {isActive ? (
          <span className="text-[11px] font-semibold text-brand-700">Currently selected</span>
        ) : (
          <span className="text-[11px] text-ink-500">Open to work on this company</span>
        )}
        <button
          type="button"
          onClick={open}
          disabled={opening}
          className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-brand-700 disabled:opacity-60"
        >
          {opening ? <Loader2 size={13} className="animate-spin" aria-hidden /> : null}
          {row.last_register_period ? "Open" : "Upload register"}
          {!opening && <ArrowRight size={13} aria-hidden />}
        </button>
      </div>
    </Card>
  );
}

export default function CompaniesPage() {
  const { isAuthenticated } = useAuth();
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["org", "portfolio"],
    queryFn: () => apiJson<Portfolio>("/api/org/portfolio"),
  });

  const message = error instanceof Error ? error.message : null;
  const notSignedIn =
    !isAuthenticated ||
    (message !== null && /\(401\)|401|not authenticated|unauthorized/i.test(message));

  if (isError && notSignedIn) {
    return (
      <div className="space-y-5">
        <SectionHeader eyebrow="Workspace" title="Companies" />
        <AlertBanner variant="warning" title="Sign in to see your companies">
          <span className="block">
            The API declined an unauthenticated request, which is what it should do.{" "}
            <Link href="/login" className="font-semibold text-brand-700 underline">
              Sign in
            </Link>{" "}
            and this page will fill in.
          </span>
        </AlertBanner>
      </div>
    );
  }

  const rows = data?.entities ?? [];
  const totals = data?.totals ?? {};

  return (
    <div className="space-y-6">
      <SectionHeader
        eyebrow="Workspace"
        title="Companies"
        description="Every employer you can see, ordered by what needs attention first."
        actions={
          <Link
            href="/payroll/upload"
            className="inline-flex h-9 items-center gap-2 rounded-lg bg-brand-600 px-3.5 text-xs font-semibold text-white transition-colors hover:bg-brand-700"
          >
            <UploadCloud size={14} aria-hidden />
            New validation run
          </Link>
        }
      />

      <SlowRequestNotice isLoading={isPending} />

      {isError && !notSignedIn && (
        <AlertBanner variant="error" title="Could not load your companies">
          <span className="block">{message}</span>
        </AlertBanner>
      )}

      {isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-44 w-full rounded-2xl" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={Building2}
          title="No companies yet"
          description="A company is the employer a register belongs to. Add one in Settings to start validating payroll."
        />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Total icon={Building2} label="Companies" value={String(totals.entities ?? rows.length)} />
            <Total icon={Users} label="People on latest registers" value={String(totals.employees ?? 0)} />
            <Total
              icon={AlertTriangle}
              label="Open findings"
              value={String(totals.open_findings ?? 0)}
              tone={(totals.critical_findings ?? 0) > 0 ? "warn" : "neutral"}
            />
            <Total
              icon={IndianRupee}
              label="Exposure across the group"
              value={inr(totals.exposure ?? 0)}
              tone={(totals.exposure ?? 0) > 0 ? "warn" : "good"}
            />
          </div>

          {(totals.awaiting_register ?? 0) > 0 && (
            <AlertBanner variant="info" title="Some companies have no register yet">
              <span className="block">
                {totals.awaiting_register} of {rows.length} have nothing uploaded. They are listed
                below with an upload button.
              </span>
            </AlertBanner>
          )}

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {rows.map((row) => (
              <CompanyCard key={row.id} row={row} />
            ))}
          </div>

          <div className="flex flex-wrap gap-2 pt-1">
            <Link
              href="/payroll/attendance"
              className="inline-flex items-center gap-2 rounded-lg border border-ink-200/70 bg-white px-3 py-2 text-xs font-semibold text-ink-700 transition-colors hover:border-brand-300 hover:text-brand-700"
            >
              <CalendarDays size={14} aria-hidden /> Attendance
            </Link>
            <Link
              href="/reconciliation"
              className="inline-flex items-center gap-2 rounded-lg border border-ink-200/70 bg-white px-3 py-2 text-xs font-semibold text-ink-700 transition-colors hover:border-brand-300 hover:text-brand-700"
            >
              <Banknote size={14} aria-hidden /> Bank &amp; JV month close
            </Link>
            <Link
              href="/cost"
              className="inline-flex items-center gap-2 rounded-lg border border-ink-200/70 bg-white px-3 py-2 text-xs font-semibold text-ink-700 transition-colors hover:border-brand-300 hover:text-brand-700"
            >
              <IndianRupee size={14} aria-hidden /> Cost analysis
            </Link>
          </div>
        </>
      )}
    </div>
  );
}
