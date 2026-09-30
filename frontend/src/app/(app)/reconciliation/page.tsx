"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Banknote,
  BookOpen,
  FileDown,
  Loader2,
  Users,
} from "lucide-react";

import { SignOffPanel } from "@/components/approvals/SignOffPanel";
import { Menu, MenuItem } from "@/components/cost/Menu";
import { PageHeader } from "@/components/layout/PageHeader";
import { Verdict } from "@/components/reconciliation/pieces";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Stat } from "@/components/ui/kpi-card";
import { useEntity } from "@/context/EntityContext";
import { periodLabel, useWorkingPeriod } from "@/lib/workspace";
import { Card, CardContent } from "@/components/ui/card";
import { apiAbsoluteUrl } from "@/lib/api";
import { formatINR } from "@/lib/cost-analysis";
import { fetchOverview, type Overview } from "@/lib/reconciliation";
import { IntegrationPanel } from "@/components/studio/IntegrationPanel";

/**
 * Where the month stands, from register to bank to ledger.
 *
 * The page is built around three claims a payroll team has to be able to make
 * at close: everyone who was due was paid, the amounts were right, and the cost
 * reached the ledger. Each one either holds, fails with named exceptions, or —
 * the state that matters — was never checked, because nothing was uploaded to
 * check it against.
 */
export default function ReconciliationOverviewPage() {
  const { entity } = useEntity();
  // The month is the working period shown in the header, so this page, the
  // Control Centre and the results never disagree about which month is meant.
  const { period, setPeriod, loading: periodLoading } = useWorkingPeriod();

  const { data, isLoading } = useQuery<Overview>({
    queryKey: ["recon-overview", entity?.id, period],
    queryFn: () => fetchOverview(period ?? undefined),
    enabled: !!entity && !periodLoading,
    placeholderData: (prev) => prev,
  });

  const periods = data?.periods ?? [];
  const selected = data?.period_label ?? (period ? periodLabel(period) : "Latest month");
  // The server reports the month asked for, register or not; say plainly when
  // there is none, rather than letting empty figures read as a quiet month.
  const noRegisterForPeriod = !!data?.period && !!period && !periods.some((p) => p.period.startsWith(period));

  return (
    <div className="space-y-5">
      <PageHeader
        title="Month close"
        description="The register against the bank file, the journal voucher against payroll cost, and the month's approval."
      />

      {noRegisterForPeriod ? (
        <AlertBanner variant="warning" title={`No register is stored for ${periodLabel(period)}`}>
          Nothing can be reconciled or approved for this month until its register is uploaded. The figures below are empty, not zero.{" "}
          <Link href="/payroll/upload" className="font-medium underline">Upload the register</Link>
        </AlertBanner>
      ) : null}

      {isLoading && (
        <Card>
          <CardContent className="flex items-center gap-2 py-10 text-sm text-ink-500">
            <Loader2 className="animate-spin" size={15} /> Reading the month…
          </CardContent>
        </Card>
      )}

      {data && data.period === null && (
        <Verdict
          state="not-compared"
          title="Nothing to reconcile yet"
          detail={data.message}
        />
      )}

      {data && data.period && (
        <>
          <div className="flex flex-wrap items-end gap-3">
            <Menu label="Period" summary={selected} width="w-56">
              {(close) => (
                <>
                  {periods.map((option) => (
                    <MenuItem
                      key={option.period}
                      selected={data.period === option.period}
                      onClick={() => {
                        setPeriod(option.period);
                        close();
                      }}
                    >
                      {option.label}
                    </MenuItem>
                  ))}
                </>
              )}
            </Menu>
            <a
              href={apiAbsoluteUrl(
                `/api/reports/bank-jv-reconciliation.xlsx?date_to=${data.period.slice(0, 7)}`,
              )}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-ink-200 bg-white px-3 text-[13px] font-medium text-ink-800 shadow-soft transition hover:bg-ink-50"
            >
              <FileDown size={14} /> Reconciliation pack
            </a>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <Stat
              label="On the register"
              value={data.register?.employees ?? null}
              qualifier={`${formatINR(data.register?.net_due ?? 0)} of net pay due · ${data.period_label}`}
            />
            <Stat
              label="Paid by bank file"
              value={data.bank?.files.length ? formatINR(data.bank.paid_total ?? 0) : "No bank file"}
              tone={data.bank?.files.length ? "neutral" : "warning"}
              qualifier={data.bank?.files.length ? `${data.bank.files.length} file(s) uploaded` : "payments cannot be reconciled until one is uploaded"}
              href="/reconciliation/bank"
            />
            <Stat
              label="Ledger mapping"
              value={data.jv?.template ? data.jv.template.name : "No approved template"}
              tone={data.jv?.template ? "neutral" : "warning"}
              qualifier={data.jv?.template ? `approved by ${data.jv.template.approved_by ?? "—"}` : "nothing can be posted to the ledger"}
              href="/config/jv-templates"
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <StepCard
              icon={Banknote}
              title="Bank payments"
              href="/reconciliation/bank"
              cta={data.bank?.ready ? "Open the reconciliation" : "Upload a bank file"}
            >
              {data.bank?.ready ? (
                <Verdict
                  state="exceptions"
                  title={`${data.bank.files.length} file(s) uploaded for ${data.period_label}`}
                  detail="Open the reconciliation to see what does not match, employee by employee."
                />
              ) : (
                <Verdict
                  state="not-compared"
                  title="Payments are unreconciled"
                  detail={data.bank?.message}
                />
              )}
            </StepCard>

            <StepCard
              icon={BookOpen}
              title="Journal voucher"
              href="/reconciliation/jv"
              cta={data.jv?.ready ? "Preview the voucher" : "Set up a template"}
            >
              {data.jv?.ready ? (
                <Verdict
                  state="clean"
                  title={`Posting with ${data.jv.template?.name}`}
                  detail="Built from the same costing the dashboard uses, so the two cannot disagree."
                />
              ) : (
                <Verdict
                  state="not-compared"
                  title="Nothing can be posted"
                  detail={data.jv?.message}
                />
              )}
            </StepCard>
          </div>

          <SignOffPanel period={data.period} />

          <IntegrationPanel period={data.period} />

          <Card>
            <CardContent className="py-5">
              <h3 className="pb-1 text-[15px] font-semibold text-ink-900">
                Reconciliations kept
              </h3>
              <p className="pb-3 text-xs text-ink-500">
                A reconciliation is only a control if it leaves a record. Closing one does
                not erase its exceptions — it records that a named person accepted them.
              </p>
              {data.runs?.length ? (
                <div className="divide-y divide-ink-200/70">
                  {data.runs.map((run) => (
                    <div
                      key={run.id}
                      className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm"
                    >
                      <span className="flex items-center gap-2 text-ink-800">
                        <Users size={13} className="text-ink-500" />
                        {run.kind === "bank" ? "Bank payments" : "Journal voucher"} ·{" "}
                        {run.period_label}
                      </span>
                      <span className="text-xs tabular-nums text-ink-500">
                        {run.exception_count} exception(s) ·{" "}
                        {run.state === "closed"
                          ? `closed by ${run.closed_by ?? "—"}`
                          : "open"}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="py-4 text-sm text-ink-500">
                  None kept for this month yet.
                </p>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

function StepCard({
  icon: Icon,
  title,
  href,
  cta,
  children,
}: {
  icon: React.ComponentType<{ size?: number | string; className?: string }>;
  title: string;
  href: string;
  cta: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardContent className="space-y-3 py-5">
        <h3 className="flex items-center gap-2 text-[15px] font-semibold text-ink-900">
          <Icon size={16} className="text-ink-500" /> {title}
        </h3>
        {children}
        <Link
          href={href}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-600 hover:underline"
        >
          {cta} <ArrowRight size={14} />
        </Link>
      </CardContent>
    </Card>
  );
}
