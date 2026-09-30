"use client";

import Link from "next/link";
import { Suspense, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { useEntity } from "@/context/EntityContext";
import { BackLink } from "@/components/layout/BackLink";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type StatusTone } from "@/components/ui/status-pill";
import { dateTime, inr } from "@/lib/format";
import { cn } from "@/lib/utils";
import { monthLabel, validationApi, type FindingExplanation } from "@/lib/validation";

/**
 * Why this result?
 *
 * One finding, with everything behind it, from what the run recorded at the
 * time: the result, the inputs, the rule and the version of it in force, the
 * arithmetic with its rounding and tolerance, the suggested correction, the
 * file and row the value came from, and who has since reviewed or approved
 * it. Nothing here is recomputed from today's configuration — the question an
 * auditor asks is what was true when the check ran.
 */

const SEVERITY_TONE: Record<string, StatusTone> = { CRITICAL: "danger", WARNING: "warning", INFO: "info" };
const SEVERITY_LABEL: Record<string, string> = { CRITICAL: "Critical", WARNING: "Warning", INFO: "Info" };
const STATE_LABEL: Record<string, string> = { open: "Open", acknowledged: "In progress", waived: "Waived", resolved: "Resolved" };

function Section({ n, title, children, className }: { n: number; title: string; children: ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-xl border border-ink-200 bg-white shadow-soft", className)} aria-labelledby={`why-${n}`}>
      <h2 id={`why-${n}`} className="flex items-center gap-2 border-b border-ink-100 px-4 py-2.5 text-[13px] font-semibold text-ink-900">
        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-ink-100 text-[11px] font-semibold text-ink-600" aria-hidden>{n}</span>
        {title}
      </h2>
      <div className="px-4 py-3">{children}</div>
    </section>
  );
}

function Rows({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[minmax(7rem,auto)_1fr] gap-x-4 gap-y-1.5 text-[13px]">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-ink-500">{k}</dt>
          <dd className="min-w-0 break-words text-ink-900">{v === null || v === undefined || v === "" ? <span className="text-ink-300">—</span> : v}</dd>
        </div>
      ))}
    </dl>
  );
}

const show = (v: unknown): ReactNode =>
  v === null || v === undefined || v === "" ? <span className="text-ink-500">not supplied</span> : typeof v === "object" ? JSON.stringify(v) : String(v);

function Explanation({ e, runId }: { e: FindingExplanation; runId: string }) {
  const policy = e.rule.policy ?? null;
  const custom = e.rule.custom_rule ?? null;
  const basis = Object.entries(e.calculation.basis ?? {});
  return (
    <div className="space-y-4">
      {/* The verdict first: what was found against what was expected. */}
      <section aria-label="The result" className="rounded-xl border border-ink-200 bg-white p-4 shadow-soft">
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill tone={SEVERITY_TONE[e.rule.severity] ?? "neutral"}>{SEVERITY_LABEL[e.rule.severity] ?? e.rule.severity}</StatusPill>
          <span className="text-[15px] font-semibold text-ink-900"><span className="font-mono text-[13px] text-ink-500">{e.rule.rule_id}</span> {e.rule.rule_name}</span>
          {e.rule.component ? <span className="text-xs text-ink-500">· {e.rule.component}</span> : null}
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
          {[
            ["Actual", e.values.actual],
            ["Expected", e.values.expected],
            ["Difference", e.values.difference],
          ].map(([k, v]) => (
            <div key={k} className="rounded-lg bg-ink-50 px-3 py-2">
              <dt className="text-xs text-ink-500">{k}</dt>
              <dd className="num mt-0.5 text-lg font-semibold text-ink-900">{v ?? <span className="text-sm font-normal text-ink-500">not recorded</span>}</dd>
            </div>
          ))}
          <div className="rounded-lg bg-ink-50 px-3 py-2">
            <dt className="text-xs text-ink-500">Financial impact</dt>
            <dd className="mt-0.5 text-lg font-semibold text-ink-900">
              {e.values.impact_calculated ? <span className="num">{inr(e.values.financial_impact, { digits: 2 })}</span> : <span className="text-sm font-normal italic text-ink-500">{e.values.impact_label ?? "Not calculated — this check does not price its effect"}</span>}
            </dd>
          </div>
        </dl>
        {e.explanation ? <p className="mt-3 max-w-4xl text-[13.5px] leading-relaxed text-ink-800">{e.explanation}</p> : null}
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <Section n={1} title="Inputs the check read">
          {Object.keys(e.inputs).length ? (
            <Rows rows={Object.entries(e.inputs).map(([k, v]) => [k.replace(/_/g, " "), show(v)])} />
          ) : (
            <p className="text-[13px] text-ink-500">No inputs were recorded for this finding.</p>
          )}
        </Section>

        <Section n={2} title="The rule and its version">
          <Rows rows={[
            ["Check", `${e.rule.rule_id} · ${e.rule.rule_name}`],
            ["Component", e.rule.component],
            ...(policy ? Object.entries(policy).map(([k, v]) => [k.replace(/_/g, " "), show(v)] as [string, ReactNode]) : []),
            ...(custom ? Object.entries(custom).map(([k, v]) => [k.replace(/_/g, " "), show(v)] as [string, ReactNode]) : []),
            ["Engine version", e.context.engine_version],
            ["Run", `Run ${e.context.run_number} (${e.context.run_status}) · ${dateTime(e.context.validated_at)}`],
          ]} />
          <p className="mt-2 text-xs text-ink-500">Statutory figures are this company&apos;s configuration at the time of the run, not a statement of law.</p>
        </Section>

        <Section n={3} title="How it was worked out" className="lg:col-span-2">
          {e.calculation.steps.length ? (
            <ol className="space-y-1.5 text-[13px] text-ink-900">
              {e.calculation.steps.map((step, i) => (
                <li key={i} className="flex gap-2.5">
                  <span className="num mt-0.5 w-5 flex-shrink-0 text-right text-xs text-ink-500">{i + 1}.</span>
                  <span className="font-mono text-[12.5px] leading-relaxed">{step}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-[13px] text-ink-500">This check compares values directly; there is no arithmetic to restate.</p>
          )}
          <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 border-t border-ink-100 pt-2 text-xs text-ink-600">
            <span>Tolerance: {e.calculation.tolerance != null ? <b className="num">₹{String(e.calculation.tolerance)}</b> : "none — exact comparison"}</span>
            {basis.map(([k, v]) => <span key={k}>{k.replace(/_/g, " ")}: <b>{String(v)}</b></span>)}
            <span className="text-ink-500">Restated from {e.calculation.reconstructed_from}.</span>
          </div>
        </Section>

        <Section n={4} title="Suggested correction">
          {e.suggested_fix ? <p className="text-[13px] leading-relaxed text-ink-900">{e.suggested_fix}</p> : <p className="text-[13px] text-ink-500">No correction is suggested for this check; the explanation above states what disagreed.</p>}
        </Section>

        <Section n={5} title="Where the value came from">
          {e.source.recorded ? (
            <Rows rows={[
              ["File", e.source.filename],
              ["Sheet", e.source.sheet],
              ["Row", e.source.row != null ? `Row ${e.source.row} (the header is row 1)` : null],
              ["Column", e.source.source_column],
              ["Value in the file", show(e.source.value)],
              ["Upload", e.source.revision != null ? `Revision ${e.source.revision}` : null],
              ["File SHA-256", e.source.file_sha256 ? <span className="font-mono text-xs" title={e.source.file_sha256}>{e.source.file_sha256.slice(0, 24)}…</span> : null],
            ]} />
          ) : (
            <p className="text-[13px] text-ink-500">This run did not keep a copy of its upload, so the source row cannot be shown. Runs made since uploads are frozen always can.</p>
          )}
        </Section>

        <Section n={6} title="Review and approval history" className="lg:col-span-2">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <Rows rows={[
                ["Review state", STATE_LABEL[e.review.state ?? "open"] ?? e.review.state],
                ["First seen", monthLabel(e.review.first_seen)],
                ["Months seen", e.review.occurrences],
                ["Waiver", e.review.waiver_reason ? `${e.review.waiver_reason}${e.review.waived_until ? ` (until ${e.review.waived_until})` : ""}` : null],
                ["Note", e.review.note],
                ["Month approval", e.approval.state ? e.approval.state.replace("_", " ") : "Not submitted"],
                ["Signed by", e.approval.signed_by],
                ["Signed on", e.approval.signed_at ? dateTime(e.approval.signed_at) : null],
              ]} />
            </div>
            <div>
              {e.review.history.length || e.approval.history.length ? (
                <ol className="space-y-2 border-l border-ink-200 pl-3 text-xs">
                  {[
                    ...e.review.history.map((h) => ({ at: h.at, text: `Finding: ${STATE_LABEL[h.from ?? ""] ?? h.from ?? "new"} → ${STATE_LABEL[h.to] ?? h.to}`, by: h.by, reason: h.reason })),
                    ...e.approval.history.map((h) => ({ at: h.at, text: `Month: ${h.from ?? "draft"} → ${h.to}`.replace(/_/g, " "), by: null as string | null, reason: h.reason })),
                  ]
                    .sort((a, b) => String(a.at).localeCompare(String(b.at)))
                    .map((h, i) => (
                      <li key={i}>
                        <p className="text-ink-900">{h.text}{h.by ? <span className="text-ink-500"> by {h.by}</span> : null}</p>
                        <p className="text-ink-500">{dateTime(h.at)}{h.reason ? ` — ${h.reason}` : ""}</p>
                      </li>
                    ))}
                </ol>
              ) : (
                <p className="text-xs text-ink-500">Nobody has reviewed this finding yet, and the month has not been submitted.</p>
              )}
            </div>
          </div>
        </Section>
      </div>

      <div className="flex flex-wrap gap-4 text-[13px]">
        <Link href={`/payroll/employee/${encodeURIComponent(e.context.employee_id)}?run=${encodeURIComponent(runId)}`} className="font-medium text-brand-700 hover:underline">
          Every check for {e.context.employee_name ?? e.context.employee_id}
        </Link>
        <Link href="/payroll/issues" className="font-medium text-brand-700 hover:underline">Work it in Issues</Link>
        <Link href="/reconciliation" className="font-medium text-brand-700 hover:underline">Month close</Link>
      </div>
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
    <div className="space-y-5">
      <BackLink fallback={runId ? `/payroll/results?run=${encodeURIComponent(runId)}&tab=findings` : "/payroll/results"}>Back to findings</BackLink>
      <PageHeader
        title="Why this result?"
        description={q.data
          ? `${q.data.context.employee_name ?? ""} · ${q.data.context.employee_id} · ${monthLabel(q.data.context.period_month)} · run ${q.data.context.run_number} (${q.data.context.run_status}) · ${q.data.context.company}`
          : "Everything behind one finding, as the run recorded it."}
      />
      {!runId || !findingId ? (
        <AlertBanner variant="info" title="No finding chosen">Open a finding from the results page and choose “Why?”.</AlertBanner>
      ) : q.isLoading ? (
        <div className="space-y-4"><Skeleton className="h-40 w-full rounded-xl" /><div className="grid gap-4 lg:grid-cols-2"><Skeleton className="h-48 rounded-xl" /><Skeleton className="h-48 rounded-xl" /></div></div>
      ) : q.error || !q.data ? (
        <AlertBanner variant="error" title="This finding could not be opened" details={q.error instanceof Error ? q.error.message : undefined}>
          It may belong to another company, or the link may be wrong.
        </AlertBanner>
      ) : (
        <Explanation e={q.data} runId={runId} />
      )}
    </div>
  );
}

export default function WhyPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full rounded-xl" />}>
      <WhyContent />
    </Suspense>
  );
}
