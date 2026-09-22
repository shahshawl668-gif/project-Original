"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, Settings2, Trash2, UploadCloud } from "lucide-react";

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
import { formatINR } from "@/lib/cost-analysis";
import {
  closeRun,
  currentPeriod,
  deleteBankFile,
  fetchBankFiles,
  fetchBankReconciliation,
  fetchProfiles,
  runReconciliation,
  uploadBankFile,
  type BankFileMeta,
} from "@/lib/reconciliation";

/**
 * Bank payments against the register.
 *
 * Upload, then reconcile, then keep the result — in that order and visibly, so
 * an operator can see which of the three they have actually done. The page
 * never shows a green state it has not earned: with no file uploaded it says
 * the month is unreconciled rather than showing an empty exception list.
 */
export default function BankReconciliationPage() {
  const queryClient = useQueryClient();
  const [period, setPeriod] = useState(currentPeriod());
  const [profileId, setProfileId] = useState<string>("");
  const [fileId, setFileId] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [kept, setKept] = useState<string | null>(null);

  const { data: profiles } = useQuery({
    queryKey: ["bank-profiles"],
    queryFn: fetchProfiles,
  });
  const { data: files, isLoading: loadingFiles } = useQuery({
    queryKey: ["bank-files", period],
    queryFn: () => fetchBankFiles(period),
  });

  useEffect(() => {
    const list = profiles?.profiles ?? [];
    if (!profileId && list.length) {
      setProfileId(list.find((p) => p.is_default)?.id ?? list[0].id);
    }
  }, [profiles, profileId]);

  useEffect(() => {
    const list = files?.files ?? [];
    setFileId(list.length ? list[0].id : "");
  }, [files]);

  const { data: result, isFetching: reconciling } = useQuery({
    queryKey: ["bank-reconcile", fileId],
    queryFn: () => fetchBankReconciliation(fileId),
    enabled: Boolean(fileId),
  });

  const upload = useMutation({
    mutationFn: (file: File) => uploadBankFile(file, period, profileId),
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["bank-files"] });
    },
    onError: (err: Error) => setError(err.message),
  });

  const keep = useMutation({
    mutationFn: async () => {
      const run = await runReconciliation({
        period_month: `${period}-01`,
        kind: "bank",
        bank_file_id: fileId,
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

  const remove = useMutation({
    mutationFn: (id: string) => deleteBankFile(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["bank-files"] }),
  });

  const profileList = profiles?.profiles ?? [];
  const fileList: BankFileMeta[] = files?.files ?? [];
  const active = fileList.find((f) => f.id === fileId);
  const summary = result?.summary;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Bank payments"
        description="What the bank file paid against what the register said was due, employee by employee."
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

      {!profileList.length && (
        <AlertBanner variant="warning" title="No bank file profile yet">
          Every bank writes its payment file differently, so this product reads yours
          through a profile you define once.{" "}
          <Link href="/config/bank-profiles" className="font-medium underline">
            Set one up
          </Link>{" "}
          — it takes a file and a column mapping.
        </AlertBanner>
      )}

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
              label="Read with"
              summary={profileList.find((p) => p.id === profileId)?.name ?? "No profile"}
              icon={Settings2}
              width="w-72"
            >
              {(close) => (
                <>
                  {profileList.map((profile) => (
                    <MenuItem
                      key={profile.id}
                      selected={profile.id === profileId}
                      onClick={() => {
                        setProfileId(profile.id);
                        close();
                      }}
                    >
                      {profile.name}
                      {profile.bank_label ? ` · ${profile.bank_label}` : ""}
                    </MenuItem>
                  ))}
                </>
              )}
            </Menu>

            <label className="inline-flex h-9 cursor-pointer items-center gap-2 rounded-lg bg-brand-600 px-3 text-sm font-medium text-white transition hover:bg-brand-700 disabled:opacity-50">
              {upload.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <UploadCloud size={14} />
              )}
              Upload bank file
              <input
                type="file"
                accept=".csv,.txt,.xlsx"
                className="hidden"
                disabled={!profileId || upload.isPending}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) upload.mutate(file);
                  event.target.value = "";
                }}
              />
            </label>
          </div>

          {loadingFiles ? (
            <p className="pt-4 text-sm text-ink-500">Loading…</p>
          ) : fileList.length ? (
            <div className="mt-4 divide-y divide-ink-200/70 dark:divide-ink-700/60">
              {fileList.map((file) => (
                <div
                  key={file.id}
                  className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm"
                >
                  <button
                    type="button"
                    onClick={() => setFileId(file.id)}
                    className="flex min-w-0 items-center gap-2 text-left"
                  >
                    <span
                      className={
                        file.id === fileId
                          ? "font-semibold text-brand-600 dark:text-brand-300"
                          : "text-ink-800 dark:text-ink-100"
                      }
                    >
                      {file.filename}
                    </span>
                    <span className="text-xs tabular-nums text-ink-500 dark:text-ink-400">
                      {file.row_count} payments · {formatINR(file.total)}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => remove.mutate(file.id)}
                    className="text-ink-400 transition hover:text-danger-600"
                    aria-label={`Delete ${file.filename}`}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="pt-4 text-sm text-ink-500 dark:text-ink-400">
              No bank file for this month. Until one is uploaded, payments for{" "}
              {period} are unreconciled.
            </p>
          )}

          {active?.problems.length ? (
            <div className="mt-3 space-y-1">
              {active.problems.map((problem) => (
                <p key={problem} className="text-xs text-warning-700 dark:text-warning-300">
                  {problem}
                </p>
              ))}
            </div>
          ) : null}
        </CardContent>
      </Card>

      {!fileId && !loadingFiles && (
        <Verdict
          state="not-compared"
          title="Nothing has been compared"
          detail="Upload the payment file your payroll team sent to the bank. Nothing on this page is a clean result until then."
        />
      )}

      {reconciling && (
        <Card>
          <CardContent className="flex items-center gap-2 py-8 text-sm text-ink-500">
            <Loader2 className="animate-spin" size={15} /> Matching payments to the register…
          </CardContent>
        </Card>
      )}

      {result && summary && (
        <>
          <Verdict
            state={summary.reconciled ? "clean" : "exceptions"}
            title={
              summary.reconciled
                ? `Reconciled — ${summary.matched} of ${summary.register_employees} paid as due`
                : `${result.counts.total} exception(s), ${formatINR(Math.abs(summary.difference))} apart`
            }
            detail={
              summary.reconciled
                ? "Every employee on the register has a matching payment for the amount due."
                : "Each exception below names the employees and the rupees behind it."
            }
          />

          <div className="grid gap-4 sm:grid-cols-3">
            <Figure
              label="Net pay due"
              value={formatINR(summary.due_total)}
              hint={`${summary.register_employees} employees on the register`}
            />
            <Figure
              label="Paid by the file"
              value={formatINR(summary.paid_total)}
              hint={`${summary.bank_rows} payment lines`}
            />
            <Figure
              label="Difference"
              value={formatINR(summary.difference)}
              hint={`tolerance ${formatINR(summary.tolerance)} per employee`}
              tone={Math.abs(summary.difference) > summary.tolerance ? "danger" : "success"}
            />
          </div>

          <Card>
            <CardContent className="py-5">
              <div className="flex flex-wrap items-center justify-between gap-3 pb-3">
                <div>
                  <h3 className="text-base font-semibold text-ink-900 dark:text-white">
                    Exceptions
                  </h3>
                  <p className="text-xs text-ink-500 dark:text-ink-400">
                    Grouped by what went wrong. Open one to see the employees behind it.
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <SeverityCounts counts={result.counts} />
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
                    Keep and close
                  </button>
                </div>
              </div>
              <ExceptionList exceptions={result.exceptions} />
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
