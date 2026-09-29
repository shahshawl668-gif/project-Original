"use client";

import Link from "next/link";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, FileSpreadsheet, Scale, ShieldCheck, Sigma, SquareCheck, UserRound } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Skeleton } from "@/components/ui/skeleton";
import { inr, monthLabel, validationApi, type FindingExplanation } from "@/lib/validation";

/**
 * Why this result?
 *
 * One finding, with everything behind it, from what the run recorded at the
 * time: the file and row the value came from, the rule and the version of it
 * in force, the arithmetic, the tolerance, and who has since reviewed or
 * approved it. Nothing here is recomputed from today's configuration — the
 * question an auditor asks is what was true when the check ran.
 */

const SECTION =
  "rounded-2xl border border-ink-200/70 bg-white p-5 shadow-soft dark:border-white/[0.07] dark:bg-ink-900/70";

function Section({ title, icon: Icon, children }: {
  title: string;
  icon: React.ComponentType<{ size?: number | string; className?: string }>;
  children: React.ReactNode;
}) {
  return (
    <section className={SECTION}>
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink-900 dark:text-white">
        <Icon size={15} className="text-brand-600" /> {title}
      </h2>
      {children}
    </section>
  );
}

function Rows({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-4 gap-y-1.5 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-ink-500 dark:text-ink-400">{k}</dt>
          <dd className="min-w-0 break-words text-ink-800 dark:text-ink-100">{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

const show = (v: unknown) =>
  v === null || v === undefined || v === "" ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v);

function Explanation({ e, runId }: { e: FindingExplanation; runId: string }) {
  const policy = e.rule.policy ?? null;
  const custom = e.rule.custom_rule ?? null;
  return (
    <div className="space-y-5">
      <AlertBanner variant={e.rule.severity === "CRITICAL" ? "error" : e.rule.severity === "WARNING" ? "warning" : "info"}
        title={`${e.rule.rule_id} · ${e.rule.rule_name}`}>
        {e.explanation ?? "No explanation was recorded."}
        {e.suggested_fix ? <p className="mt-2"><strong>Fix:</strong> {e.suggested_fix}</p> : null}
      </AlertBanner>

      <div className="grid gap-5 lg:grid-cols-2">
        <Section title="The result" icon={Scale}>
          <Rows rows={[
            ["Expected", e.values.expected],
            ["Found", e.values.actual],
            ["Difference", e.values.difference],
            ["Financial impact", e.values.impact_calculated
              ? inr(e.values.financial_impact, 2)
              : <em className="text-ink-500">{e.values.impact_label ?? "Impact not calculated"}</em>],
            ["Severity", e.rule.severity],
          ]} />
        </Section>

        <Section title="Where the value came from" icon={FileSpreadsheet}>
          {e.source.recorded ? (
            <Rows rows={[
              ["File", e.source.filename],
              ["Sheet", e.source.sheet],
              ["Row", e.source.row != null ? `row ${e.source.row} (header is row 1)` : "—"],
              ["Column", e.source.source_column],
              ["Value in the file", show(e.source.value)],
              ["Upload", e.source.revision != null ? `revision ${e.source.revision}` : "—"],
              ["File SHA-256", <span key="h" className="font-mono text-xs">{e.source.file_sha256?.slice(0, 24)}…</span>],
            ]} />
          ) : (
            <p className="text-sm text-ink-500">
              This run did not keep a copy of its upload, so the source row cannot be shown. Runs made since uploads are
              frozen always can.
            </p>
          )}
        </Section>

        <Section title="How it was worked out" icon={Sigma}>
          {e.calculation.steps.length ? (
            <ol className="list-decimal space-y-1 pl-5 text-sm text-ink-800 dark:text-ink-100">
              {e.calculation.steps.map((step, i) => <li key={i}>{step}</li>)}
            </ol>
          ) : (
            <p className="text-sm text-ink-500">This check compares values directly; there is no arithmetic to restate.</p>
          )}
          {e.calculation.tolerance != null ? (
            <p className="mt-2 text-xs text-ink-500">Tolerance applied: ₹{show(e.calculation.tolerance)}</p>
          ) : null}
          {Object.keys(e.inputs).length ? (
            <div className="mt-3">
              <p className="mb-1 text-xs font-semibold text-ink-600 dark:text-ink-300">Inputs read from the register</p>
              <Rows rows={Object.entries(e.inputs).map(([k, v]) => [k, show(v)])} />
            </div>
          ) : null}
          <p className="mt-3 text-[11px] text-ink-400">Restated from {e.calculation.reconstructed_from}.</p>
        </Section>

        <Section title="The rule in force" icon={SquareCheck}>
          <Rows rows={[
            ["Check", `${e.rule.rule_id} · ${e.rule.rule_name}`],
            ["Component", e.rule.component],
            ...(policy ? Object.entries(policy).map(([k, v]) => [k.replace(/_/g, " "), show(v)] as [string, React.ReactNode]) : []),
            ...(custom ? Object.entries(custom).map(([k, v]) => [k.replace(/_/g, " "), show(v)] as [string, React.ReactNode]) : []),
            ["Engine version", e.context.engine_version],
          ]} />
          <p className="mt-2 text-[11px] text-ink-400">
            Statutory figures shown are this company&apos;s configuration at the time of the run, not a statement of law.
          </p>
        </Section>

        <Section title="Review" icon={UserRound}>
          <Rows rows={[
            ["Status now", e.review.state ?? "open"],
            ["First seen", monthLabel(e.review.first_seen)],
            ["Months seen", e.review.occurrences],
            ["Waiver", e.review.waiver_reason
              ? `${e.review.waiver_reason}${e.review.waived_until ? ` (until ${e.review.waived_until})` : ""}` : "—"],
            ["Note", e.review.note],
          ]} />
          {e.review.history.length ? (
            <ul className="mt-3 space-y-1 text-xs text-ink-600 dark:text-ink-300">
              {e.review.history.map((h, i) => (
                <li key={i}>
                  {h.at ? new Date(h.at).toLocaleString("en-IN") : "—"} · {h.from ?? "new"} → {h.to} by {h.by ?? "—"}
                  {h.reason ? ` — ${h.reason}` : ""}
                </li>
              ))}
            </ul>
          ) : null}
        </Section>

        <Section title="Approval" icon={ShieldCheck}>
          <Rows rows={[
            ["Month", e.approval.state ? e.approval.state.replace("_", " ") : "not submitted"],
            ["Signed by", e.approval.signed_by],
            ["Signed on", e.approval.signed_at ? new Date(e.approval.signed_at).toLocaleString("en-IN") : "—"],
          ]} />
          <Link href="/reconciliation" className="mt-3 inline-block text-xs font-semibold text-brand-700 hover:underline dark:text-brand-300">
            Open Month close
          </Link>
        </Section>
      </div>

      <Link href={`/payroll/employee/${encodeURIComponent(e.context.employee_id)}?run=${encodeURIComponent(runId)}`}
        className="inline-flex items-center gap-1 text-sm font-semibold text-brand-700 hover:underline dark:text-brand-300">
        Every check for {e.context.employee_id}
      </Link>
    </div>
  );
}

function WhyContent() {
  const params = useSearchParams();
  const { entity } = useEntity();
  const runId = params.get("run") ?? "";
  const findingId = params.get("finding") ?? "";
  const q = useQuery<FindingExplanation>({
    queryKey: ["explain", entity?.id, runId, findingId],
    queryFn: () => validationApi.explain(runId, findingId),
    enabled: !!runId && !!findingId,
    retry: false,
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Why this result?"
        description={q.data
          ? `${q.data.context.employee_id}${q.data.context.employee_name ? ` · ${q.data.context.employee_name}` : ""} · ${monthLabel(q.data.context.period_month)} · run #${q.data.context.run_number} (${q.data.context.run_status})`
          : "Everything behind one finding, as the run recorded it."}
        actions={
          <Link href={runId ? `/payroll/results?run=${encodeURIComponent(runId)}&tab=findings` : "/payroll/results"}
            className="inline-flex h-9 items-center gap-2 rounded-lg border border-ink-200 px-3 text-sm font-medium text-ink-700 hover:bg-ink-50 dark:border-ink-700 dark:text-ink-200 dark:hover:bg-ink-800">
            <ArrowLeft size={14} /> Findings
          </Link>
        }
      />
      {!runId || !findingId ? (
        <AlertBanner variant="info" title="No finding chosen">
          Open a finding from the results page and choose “Why this result?”.
        </AlertBanner>
      ) : q.isLoading ? (
        <Skeleton className="h-96 w-full rounded-2xl" />
      ) : q.error || !q.data ? (
        <AlertBanner variant="error" title="This finding could not be opened">
          {q.error instanceof Error ? q.error.message : "Not found."} It may belong to another company.
        </AlertBanner>
      ) : (
        <Explanation e={q.data} runId={runId} />
      )}
    </div>
  );
}

export default function WhyPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full rounded-2xl" />}>
      <WhyContent />
    </Suspense>
  );
}
