"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileDown, Loader2, ScrollText } from "lucide-react";

import { Menu, MenuItem } from "@/components/cost/Menu";
import { PageHeader } from "@/components/layout/PageHeader";
import {
  ExceptionList,
  Figure,
  SeverityCounts,
  Verdict,
} from "@/components/reconciliation/pieces";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import { apiAbsoluteUrl } from "@/lib/api";
import { formatINR } from "@/lib/cost-analysis";
import {
  closeRun,
  currentPeriod,
  fetchJvOptions,
  fetchJvReconciliation,
  fetchTemplates,
  runReconciliation,
} from "@/lib/reconciliation";

/**
 * The journal voucher, and whether it agrees with payroll cost.
 *
 * The voucher is built from the same costing pass as the cost dashboard, so a
 * disagreement here is always a mapping problem and never a data one. That is
 * what makes the imbalance worth reporting in rupees: it names a measure with
 * no account rather than a mystery.
 */
export default function JvPage() {
  const queryClient = useQueryClient();
  const [period, setPeriod] = useState(currentPeriod());
  const [templateId, setTemplateId] = useState<string>("");
  const [format, setFormat] = useState<string>("");
  const [kept, setKept] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: templates } = useQuery({ queryKey: ["jv-templates"], queryFn: fetchTemplates });
  const { data: options } = useQuery({ queryKey: ["jv-options"], queryFn: fetchJvOptions });

  useEffect(() => {
    const list = templates?.templates ?? [];
    if (!templateId && list.length) {
      setTemplateId(list.find((t) => t.is_current)?.id ?? list[0].id);
    }
  }, [templates, templateId]);

  const template = templates?.templates.find((t) => t.id === templateId);

  useEffect(() => {
    if (template && !format) setFormat(template.export_format);
  }, [template, format]);

  const { data: result, isFetching } = useQuery({
    queryKey: ["jv-reconcile", period, templateId],
    queryFn: () => fetchJvReconciliation(period, templateId),
    enabled: Boolean(templateId),
  });

  const keep = useMutation({
    mutationFn: async () => {
      const run = await runReconciliation({
        period_month: `${period}-01`,
        kind: "jv",
        jv_template_id: templateId,
      });
      await closeRun(run.id);
      return run;
    },
    onSuccess: (run) => {
      setKept(`Kept and closed — ${run.exception_count} exception(s) on the record.`);
      queryClient.invalidateQueries({ queryKey: ["recon-overview"] });
    },
    onError: (err: Error) => setError(err.message),
  });

  const list = templates?.templates ?? [];
  const summary = result?.summary;
  const formats = options?.export_formats ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Journal voucher"
        description="The month's payroll cost, posted the way your company posts it."
      />

      {error && (
        <AlertBanner variant="error" title="That did not work">
          {error}
        </AlertBanner>
      )}
      {kept && (
        <AlertBanner variant="success" title="On the record">
          {kept}
        </AlertBanner>
      )}

      {!list.length && (
        <AlertBanner variant="warning" title="No JV template yet">
          There is no standard payroll journal voucher — the accounts are your chart, and
          the split is whatever your ERP posts by.{" "}
          <Link href="/config/jv-templates" className="font-medium underline">
            Start from a supplied template
          </Link>{" "}
          and change the account codes to your own.
        </AlertBanner>
      )}

      {list.length > 0 && (
        <Card>
          <CardContent className="py-5">
            <div className="flex flex-wrap items-end gap-3">
              <div>
                <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                  Period
                </span>
                <input
                  type="month"
                  value={period}
                  onChange={(event) => setPeriod(event.target.value)}
                  className="h-9 rounded-lg border border-ink-200 bg-white px-3 text-sm text-ink-900 dark:border-ink-700 dark:bg-ink-900 dark:text-white"
                />
              </div>

              <Menu
                label="Template"
                summary={template?.name ?? "Choose one"}
                icon={ScrollText}
                width="w-72"
              >
                {(close) => (
                  <>
                    {list.map((item) => (
                      <MenuItem
                        key={item.id}
                        selected={item.id === templateId}
                        onClick={() => {
                          setTemplateId(item.id);
                          close();
                        }}
                      >
                        {item.name}
                        {item.is_current ? " · current" : item.state === "draft" ? " · draft" : ""}
                      </MenuItem>
                    ))}
                  </>
                )}
              </Menu>

              <Menu
                label="Export as"
                summary={formats.find((f) => f.key === format)?.label ?? "Generic CSV"}
                width="w-72"
              >
                {(close) => (
                  <>
                    {formats.map((option) => (
                      <MenuItem
                        key={option.key}
                        selected={option.key === format}
                        onClick={() => {
                          setFormat(option.key);
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
                  `/api/reconciliation/jv/export?period=${period}&template_id=${templateId}&format=${format || "generic_csv"}`,
                )}
                className="inline-flex h-9 items-center gap-2 rounded-lg border border-ink-200 px-3 text-sm font-medium text-ink-700 transition hover:bg-ink-50 dark:border-ink-700 dark:text-ink-200 dark:hover:bg-ink-800"
              >
                <FileDown size={14} /> Download voucher
              </a>
            </div>

            {template && template.state === "draft" && (
              <p className="pt-3 text-xs text-warning-700 dark:text-warning-300">
                This template is a draft. It can be previewed and exported, but an owner or
                manager has to approve it before it is the mapping this entity posts with.
              </p>
            )}
            <p className="pt-3 text-xs text-ink-500 dark:text-ink-400">
              The export is shaped like the target system&apos;s import file, which is not the
              same as being its specification. Run the first month through your accounting
              system&apos;s own import preview before trusting it.
            </p>
          </CardContent>
        </Card>
      )}

      {isFetching && (
        <Card>
          <CardContent className="flex items-center gap-2 py-8 text-sm text-ink-500">
            <Loader2 className="animate-spin" size={15} /> Building the voucher…
          </CardContent>
        </Card>
      )}

      {result && summary && (
        <>
          <Verdict
            state={summary.reconciled ? "clean" : "exceptions"}
            title={
              summary.reconciled
                ? `Balanced — ${formatINR(summary.total_debit)} posted across ${summary.lines} lines`
                : `${result.counts.total} problem(s) with this mapping`
            }
            detail={
              summary.reconciled
                ? "Debits equal credits and equal the month's payroll cost, so the ledger and the dashboard agree."
                : "A correct mapping balances by arithmetic, so a difference names a measure posted on one side only."
            }
          />

          <div className="grid gap-4 sm:grid-cols-4">
            <Figure label="Debits" value={formatINR(summary.total_debit)} />
            <Figure label="Credits" value={formatINR(summary.total_credit)} />
            <Figure
              label="Out of balance"
              value={formatINR(summary.difference)}
              tone={summary.difference === 0 ? "success" : "danger"}
            />
            <Figure
              label="Payroll cost"
              value={formatINR(summary.payroll_cost)}
              hint={`${summary.employee_count} employees`}
            />
          </div>

          {result.counts.total > 0 && (
            <Card>
              <CardContent className="py-5">
                <div className="flex flex-wrap items-center justify-between gap-3 pb-3">
                  <h3 className="text-base font-semibold text-ink-900 dark:text-white">
                    What is wrong with the mapping
                  </h3>
                  <SeverityCounts counts={result.counts} />
                </div>
                <ExceptionList exceptions={result.exceptions} />
              </CardContent>
            </Card>
          )}

          {result.vouchers.map((voucher) => (
            <Card key={voucher.number}>
              <CardContent className="py-5">
                <div className="flex flex-wrap items-center justify-between gap-2 pb-3">
                  <div>
                    <h3 className="text-base font-semibold text-ink-900 dark:text-white">
                      {voucher.number}
                      {voucher.scope ? ` · ${voucher.scope}` : ""}
                    </h3>
                    <p className="text-xs text-ink-500 dark:text-ink-400">
                      {voucher.type} dated {voucher.date} — {voucher.narration}
                    </p>
                  </div>
                  <span
                    className={
                      voucher.balanced
                        ? "text-xs font-semibold text-success-700 dark:text-success-400"
                        : "text-xs font-semibold text-danger-600 dark:text-danger-400"
                    }
                  >
                    {voucher.balanced
                      ? "Balanced"
                      : `Out by ${formatINR(Math.abs(voucher.difference))}`}
                  </span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-ink-200 text-left text-[10px] uppercase tracking-wide text-ink-400 dark:border-ink-700">
                        <th className="py-2 pr-3 font-semibold">Account</th>
                        <th className="py-2 pr-3 font-semibold">Cost centre</th>
                        <th className="py-2 pr-3 text-right font-semibold">Debit</th>
                        <th className="py-2 text-right font-semibold">Credit</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-ink-200/70 dark:divide-ink-700/60">
                      {voucher.lines.map((line, index) => (
                        <tr key={`${line.account_code}-${line.label}-${index}`}>
                          <td className="py-2 pr-3">
                            <span className="font-medium text-ink-900 dark:text-white">
                              {line.account_code}
                            </span>
                            <span className="block text-xs text-ink-500 dark:text-ink-400">
                              {line.label}
                            </span>
                          </td>
                          <td className="py-2 pr-3 text-xs text-ink-500 dark:text-ink-400">
                            {line.cost_center ?? "—"}
                          </td>
                          <td className="py-2 pr-3 text-right tabular-nums text-ink-800 dark:text-ink-100">
                            {line.debit ? formatINR(line.debit) : ""}
                          </td>
                          <td className="py-2 text-right tabular-nums text-ink-800 dark:text-ink-100">
                            {line.credit ? formatINR(line.credit) : ""}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr className="border-t-2 border-ink-300 font-semibold dark:border-ink-600">
                        <td className="py-2 pr-3 text-ink-900 dark:text-white" colSpan={2}>
                          Total
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums text-ink-900 dark:text-white">
                          {formatINR(voucher.total_debit)}
                        </td>
                        <td className="py-2 text-right tabular-nums text-ink-900 dark:text-white">
                          {formatINR(voucher.total_credit)}
                        </td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              </CardContent>
            </Card>
          ))}

          {result.vouchers.length > 0 && (
            <button
              type="button"
              onClick={() => keep.mutate()}
              disabled={keep.isPending}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-ink-200 px-3 text-sm font-medium text-ink-700 transition hover:bg-ink-50 disabled:opacity-50 dark:border-ink-700 dark:text-ink-200 dark:hover:bg-ink-800"
            >
              {keep.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <CheckCircle2 size={14} />
              )}
              Keep this check on the record
            </button>
          )}
        </>
      )}
    </div>
  );
}
