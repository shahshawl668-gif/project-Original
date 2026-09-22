"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Banknote,
  BookOpen,
  FileDown,
  Loader2,
  Users,
} from "lucide-react";

import { Menu, MenuItem } from "@/components/cost/Menu";
import { PageHeader } from "@/components/layout/PageHeader";
import { Figure, Verdict } from "@/components/reconciliation/pieces";
import { Card, CardContent } from "@/components/ui/card";
import { apiAbsoluteUrl } from "@/lib/api";
import { formatINR } from "@/lib/cost-analysis";
import { fetchOverview, type Overview } from "@/lib/reconciliation";

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
  const [period, setPeriod] = useState<string | undefined>(undefined);

  const { data, isLoading } = useQuery<Overview>({
    queryKey: ["recon-overview", period],
    queryFn: () => fetchOverview(period),
  });

  const periods = data?.periods ?? [];
  const selected = data?.period_label ?? "Latest month";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Reconciliation"
        description="The register against the bank file, and the journal voucher against payroll cost."
      />

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
                      key={option.key}
                      selected={data.period?.startsWith(option.key) ?? false}
                      onClick={() => {
                        setPeriod(option.key);
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
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-ink-200 px-3 text-sm font-medium text-ink-700 transition hover:bg-ink-50 dark:border-ink-700 dark:text-ink-200 dark:hover:bg-ink-800"
            >
              <FileDown size={14} /> Reconciliation pack
            </a>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <Figure
              label="On the register"
              value={`${data.register?.employees ?? 0}`}
              hint={`${formatINR(data.register?.net_due ?? 0)} of net pay due`}
            />
            <Figure
              label="Paid by bank file"
              value={formatINR(data.bank?.paid_total ?? 0)}
              hint={
                data.bank?.files.length
                  ? `${data.bank.files.length} file(s) uploaded`
                  : "no file uploaded"
              }
              tone={data.bank?.ready ? "neutral" : "danger"}
            />
            <Figure
              label="Ledger mapping"
              value={data.jv?.template ? data.jv.template.name : "None"}
              hint={
                data.jv?.template
                  ? `approved by ${data.jv.template.approved_by ?? "—"}`
                  : "no approved template"
              }
              tone={data.jv?.ready ? "neutral" : "danger"}
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

          <Card>
            <CardContent className="py-5">
              <h3 className="pb-1 text-base font-semibold text-ink-900 dark:text-white">
                Reconciliations kept
              </h3>
              <p className="pb-3 text-xs text-ink-500 dark:text-ink-400">
                A reconciliation is only a control if it leaves a record. Closing one does
                not erase its exceptions — it records that a named person accepted them.
              </p>
              {data.runs?.length ? (
                <div className="divide-y divide-ink-200/70 dark:divide-ink-700/60">
                  {data.runs.map((run) => (
                    <div
                      key={run.id}
                      className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm"
                    >
                      <span className="flex items-center gap-2 text-ink-800 dark:text-ink-100">
                        <Users size={13} className="text-ink-400" />
                        {run.kind === "bank" ? "Bank payments" : "Journal voucher"} ·{" "}
                        {run.period_label}
                      </span>
                      <span className="text-xs tabular-nums text-ink-500 dark:text-ink-400">
                        {run.exception_count} exception(s) ·{" "}
                        {run.state === "closed"
                          ? `closed by ${run.closed_by ?? "—"}`
                          : "open"}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="py-4 text-sm text-ink-500 dark:text-ink-400">
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
        <h3 className="flex items-center gap-2 text-base font-semibold text-ink-900 dark:text-white">
          <Icon size={16} className="text-ink-400" /> {title}
        </h3>
        {children}
        <Link
          href={href}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-600 hover:underline dark:text-brand-300"
        >
          {cta} <ArrowRight size={14} />
        </Link>
      </CardContent>
    </Card>
  );
}
