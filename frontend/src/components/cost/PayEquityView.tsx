"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { EyeOff, Info, Lock, ScaleIcon, ShieldCheck, Users } from "lucide-react";

import { ClickHint, DivergingBar, Panel } from "@/components/cost/pieces";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  chartTheme,
  describeGap,
  DIVERGING,
  OTHER_COLOR,
  fetchPayEquity,
  fetchPayEquitySettings,
  formatINR,
  setPayEquityEnabled,
  type GenderSummary,
  type PayEquity,
} from "@/lib/cost-analysis";
import { cn } from "@/lib/utils";

/** A gap against women reads as a problem; a gap the other way is still a gap. */
function toneClass(tone: string) {
  if (tone === "gap") return "text-danger-600 dark:text-danger-400";
  if (tone === "reverse") return "text-accent-700 dark:text-accent-400";
  if (tone === "level") return "text-success-700 dark:text-success-400";
  return "text-ink-400";
}

export function PayEquityView({
  groupBy,
  filters,
  palette,
  onSelectGroup,
}: {
  groupBy: string;
  filters: Record<string, string[]>;
  palette: string[];
  onSelectGroup?: (group: string) => void;
}) {
  const settings = useQuery({
    queryKey: ["pay-equity", "settings"],
    queryFn: fetchPayEquitySettings,
  });
  const enabled = settings.data?.enabled ?? false;

  const analysis = useQuery({
    queryKey: ["pay-equity", groupBy, filters],
    queryFn: () => fetchPayEquity({ groupBy, filters }),
    enabled,
  });

  if (settings.isLoading) return <Skeleton className="h-64" />;
  if (!enabled) return <AuthorisationGate canChange={settings.data?.can_change ?? false} />;
  if (analysis.isError) {
    return (
      <AlertBanner variant="error" title="Could not load the pay equity analysis">
        {(analysis.error as Error).message}
      </AlertBanner>
    );
  }
  if (analysis.isLoading || !analysis.data) return <Skeleton className="h-64" />;

  return (
    <Analysis data={analysis.data} settings={settings.data} palette={palette} onSelectGroup={onSelectGroup} />
  );
}

/* ── the gate ─────────────────────────────────────────────────────────── */

function AuthorisationGate({ canChange }: { canChange: boolean }) {
  const queryClient = useQueryClient();
  const [note, setNote] = useState("");

  const enable = useMutation({
    mutationFn: () => setPayEquityEnabled(true, note),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["pay-equity"] }),
  });

  return (
    <Card>
      <CardContent className="space-y-4 py-6">
        <span className="flex items-center gap-2 text-sm font-semibold text-ink-900 dark:text-white">
          <Lock size={15} className="text-ink-400" /> Gender pay gap analysis is switched off
        </span>
        <div className="max-w-[68ch] space-y-3 text-sm text-ink-600 dark:text-ink-300">
          <p>
            Indian law requires no gender pay gap reporting, so whether to run this analysis is
            the employer&rsquo;s decision rather than this product&rsquo;s. Switching it on is
            recorded against this entity with your name and the date — and on a workspace holding
            several client companies, it enables the analysis for this one only.
          </p>
          <p>Once it is on:</p>
          <ul className="list-disc space-y-1 pl-5">
            <li>only owners and managers can read it — not the analyst tier that can see individual salaries;</li>
            <li>no individual employee is ever shown, at any permission level;</li>
            <li>any group with fewer than five people of one gender is withheld, because a median over a handful of people discloses their pay;</li>
            <li>every view is written to the audit trail.</li>
          </ul>
        </div>

        {canChange ? (
          <div className="flex max-w-[52ch] flex-col gap-2 pt-1">
            <label className="flex flex-col gap-1.5">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                What authorises this? (optional, kept in the audit trail)
              </span>
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="e.g. Board approval, 12 March"
                className="h-9 rounded-lg border border-ink-200 bg-white px-3 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-brand-500 dark:border-white/10 dark:bg-white/[0.04] dark:text-white"
              />
            </label>
            <button
              type="button"
              onClick={() => enable.mutate()}
              disabled={enable.isPending}
              className="inline-flex w-fit items-center gap-1.5 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-700 disabled:opacity-50"
            >
              <ShieldCheck size={14} /> Authorise and switch on
            </button>
            {enable.isError && (
              <p className="text-xs text-danger-600 dark:text-danger-400">
                {(enable.error as Error).message}
              </p>
            )}
          </div>
        ) : (
          <p className="text-sm text-ink-500 dark:text-ink-400">
            An owner or manager can switch it on.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

/* ── the analysis ─────────────────────────────────────────────────────── */

function Analysis({
  data,
  settings,
  palette,
  onSelectGroup,
}: {
  data: PayEquity;
  settings?: { enabled_by: string | null; can_change: boolean };
  palette: string[];
  onSelectGroup?: (group: string) => void;
}) {
  const queryClient = useQueryClient();
  const disable = useMutation({
    mutationFn: () => setPayEquityEnabled(false),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["pay-equity"] }),
  });

  const headline = data.headline;
  const median = describeGap(headline?.median_gap_pct ?? null);
  const mean = describeGap(headline?.mean_gap_pct ?? null);
  const variable = describeGap(headline?.variable_gap_pct ?? null);
  const coverage = data.coverage;

  const chrome = chartTheme();
  const axisTick = chrome.tick;
  const gridColor = chrome.grid;
  const diverging = DIVERGING;
  const quartileData = data.quartiles.map((q) => ({
    band: q.band,
    Women: q.counts.female,
    Men: q.counts.male,
    "Other / self-described": q.counts.other,
    "Not recorded": q.counts.not_recorded,
  }));
  const comparable = data.like_for_like.filter((g) => g.comparable);

  return (
    <div className="space-y-5">
      {/* ── coverage first: every figure below depends on it ───────── */}
      <Panel
        title={`Population — ${data.period_label}`}
        description={data.basis}
        actions={
          settings?.can_change ? (
            <button
              type="button"
              onClick={() => disable.mutate()}
              disabled={disable.isPending}
              className="rounded-lg border border-ink-200 px-2.5 py-1.5 text-xs font-medium text-ink-600 hover:bg-ink-50 disabled:opacity-60 dark:border-white/10 dark:text-ink-300 dark:hover:bg-white/[0.06]"
            >
              Switch off
            </button>
          ) : undefined
        }
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {coverage.by_gender.map((row) => (
            <div key={row.key} className="rounded-xl border border-ink-200/70 px-3 py-2.5 dark:border-white/10">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                {row.label}
              </p>
              <p className="font-display text-xl font-semibold tabular-nums text-ink-900 dark:text-white">
                {row.count}
              </p>
            </div>
          ))}
          <div className="rounded-xl border border-ink-200/70 px-3 py-2.5 dark:border-white/10">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">
              Gender recorded
            </p>
            <p className="font-display text-xl font-semibold tabular-nums text-ink-900 dark:text-white">
              {coverage.recorded_pct.toFixed(0)}%
            </p>
            <p className="text-[11px] text-ink-500 dark:text-ink-400">
              {coverage.recorded} of {coverage.total}
            </p>
          </div>
        </div>

        {coverage.recorded_pct < 90 && (
          <p className="mt-3 flex items-start gap-2 rounded-lg border border-warning-200 bg-warning-50 px-3 py-2 text-xs text-warning-800 dark:border-warning-500/30 dark:bg-warning-500/10 dark:text-warning-300">
            <Info size={14} className="mt-px flex-shrink-0" />
            <span>
              {coverage.total - coverage.recorded} employee
              {coverage.total - coverage.recorded === 1 ? " has" : "s have"} no gender on the
              employee master. They are counted here and excluded from every figure below.
              Low coverage makes these numbers less reliable, not more favourable.
            </span>
          </p>
        )}
      </Panel>

      {/* ── the headline gap ───────────────────────────────────────── */}
      <Panel
        title="Unadjusted gap"
        description="Everyone against everyone. This mostly reflects which roles are held by whom — it is not a measure of unequal pay for the same work."
      >
        {headline?.comparable ? (
          <div className="grid gap-4 sm:grid-cols-3">
            <GapTile label="Median gap" gap={median} detail="The middle woman against the middle man" />
            <GapTile label="Mean gap" gap={mean} detail="Moved by a few large packages; the median is not" />
            <GapTile label="Variable pay gap" gap={variable} detail="Median bonus and incentive, compared separately" />
          </div>
        ) : (
          <p className="rounded-lg border border-ink-200/70 bg-ink-50 px-3 py-2.5 text-sm text-ink-600 dark:border-white/10 dark:bg-white/[0.03] dark:text-ink-300">
            {headline?.reason ??
              "Not enough of the population has a gender recorded to compare."}
          </p>
        )}

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <GenderCard label="Women" summary={headline?.women} palette={palette[0]} />
          <GenderCard label="Men" summary={headline?.men} palette={palette[4]} />
        </div>

        <p className="mt-3 flex items-start gap-2 text-xs text-ink-500 dark:text-ink-400">
          <ScaleIcon size={13} className="mt-px flex-shrink-0" />
          <span>{data.direction}</span>
        </p>
      </Panel>

      {/* ── representation ─────────────────────────────────────────── */}
      <Panel
        title="Pay quartiles"
        description="Everyone sorted by pay and split into four equal bands. This is the measure that shows representation directly — an organisation can pay equally within every grade and still have every woman in the lowest band."
      >
        <div className="h-[280px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={quartileData} layout="vertical"
                      margin={{ top: 8, right: 16, left: 8, bottom: 0 }}>
              <CartesianGrid stroke={gridColor} horizontal={false} />
              <XAxis type="number" tick={axisTick} tickLine={false} axisLine={false}
                     allowDecimals={false} />
              <YAxis type="category" dataKey="band" width={104} tick={axisTick}
                     tickLine={false} axisLine={false} />
              <Tooltip
                cursor={{ fill: "rgba(14,18,32,0.04)" }}
                contentStyle={{
                  background: "#ffffff",
                  border: `1px solid ${"#d6dae3"}`,
                  borderRadius: 8, fontSize: 12,
                  color: "#1b2030",
                }}
              />
              <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12, paddingTop: 12 }} />
              {/* A 2px stroke in the surface colour, so adjacent segments are
                  separated by a gap rather than by hue alone — which is what
                  keeps them apart for a reader with colour-vision deficiency. */}
              <Bar dataKey="Women" stackId="q" fill={palette[0]} stroke={chrome.surface} strokeWidth={2} />
              <Bar dataKey="Men" stackId="q" fill={palette[4]} stroke={chrome.surface} strokeWidth={2} />
              <Bar dataKey="Other / self-described" stackId="q" fill={palette[2]} stroke={chrome.surface} strokeWidth={2} />
              <Bar dataKey="Not recorded" stackId="q" fill={OTHER_COLOR} stroke={chrome.surface} strokeWidth={2} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-ink-200 text-[10px] uppercase tracking-wide text-ink-400 dark:border-white/10">
                <th className="py-2 text-left font-semibold">Band</th>
                <th className="py-2 text-left font-semibold">Pay range</th>
                <th className="py-2 text-right font-semibold">Employees</th>
                <th className="py-2 text-right font-semibold">Women</th>
                <th className="py-2 text-right font-semibold">Men</th>
                <th className="py-2 text-right font-semibold">Women % of known</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {data.quartiles.map((q) => (
                <tr key={q.band} className="border-b border-ink-100 last:border-0 dark:border-white/5">
                  <td className="py-2 pr-3 text-ink-800 dark:text-ink-100">{q.band}</td>
                  <td className="py-2 pr-3 text-ink-500 dark:text-ink-400">
                    {q.pay_from !== null && q.pay_to !== null
                      ? `${formatINR(q.pay_from, true)} – ${formatINR(q.pay_to, true)}`
                      : "—"}
                  </td>
                  <td className="py-2 text-right text-ink-900 dark:text-white">{q.count}</td>
                  <td className="py-2 text-right text-ink-600 dark:text-ink-300">{q.counts.female}</td>
                  <td className="py-2 text-right text-ink-600 dark:text-ink-300">{q.counts.male}</td>
                  <td className="py-2 text-right text-ink-900 dark:text-white">
                    {q.female_pct === null ? "—" : `${q.female_pct.toFixed(0)}%`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* ── the gap itself, as a signed quantity ───────────────────── */}
      <Panel
        title={`Gap by ${data.group_by_label.toLowerCase()}`}
        description="Each comparable group's median gap, measured from zero. Bars to the right are groups where women are paid less; bars to the left, more."
      >
        {comparable.length === 0 ? (
          <div className="rounded-lg border border-ink-200/70 bg-ink-50 px-3.5 py-3 text-sm text-ink-600 dark:border-white/10 dark:bg-white/[0.03] dark:text-ink-300">
            <p className="font-medium text-ink-800 dark:text-ink-100">Nothing can be charted yet.</p>
            <p className="mt-1">
              None of the {data.like_for_like.length} groups has at least {data.min_group_size} of
              each gender, so every median would disclose someone&rsquo;s pay. A like-for-like
              comparison needs a few hundred employees before many groups clear that bar — the
              headline gap and the quartiles above are the measures that work at this size.
            </p>
          </div>
        ) : (
          <>
            {onSelectGroup && (
              <ClickHint>
                Click a bar to filter the page to that {data.group_by_label.toLowerCase()}.
              </ClickHint>
            )}
            <div style={{ height: Math.max(180, comparable.length * 44) }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={comparable.map((g) => ({ name: g.group, gap: g.median_gap_pct ?? 0 }))}
                  layout="vertical"
                  margin={{ top: 8, right: 24, left: 8, bottom: 4 }}
                >
                  <CartesianGrid stroke={gridColor} horizontal={false} />
                  <XAxis type="number" tick={axisTick} tickLine={false} axisLine={false}
                         tickFormatter={(v: number) => `${v > 0 ? "+" : ""}${v}%`} />
                  <YAxis type="category" dataKey="name" width={124} tick={axisTick}
                         tickLine={false} axisLine={false} />
                  <Tooltip cursor={{ fill: chrome.cursor }} content={<GapTooltip chrome={chrome} />} />
                  {/* Zero is the thing the eye measures from, so it gets a rule
                      of its own rather than blending into the grid. */}
                  <ReferenceLine x={0} stroke={chrome.muted} strokeWidth={1.5} />
                  <Bar
                    dataKey="gap"
                    barSize={20}
                    cursor={onSelectGroup ? "pointer" : undefined}
                    onClick={(entry: { name?: string }) => entry?.name && onSelectGroup?.(entry.name)}
                    shape={(props: { x?: number; y?: number; width?: number; height?: number; payload?: unknown }) => (
                      <DivergingBar
                        x={props.x}
                        y={props.y}
                        width={props.width}
                        height={props.height}
                        value={(props.payload as { gap: number } | undefined)?.gap ?? 0}
                        palette={diverging}
                      />
                    )}
                  >
                    {comparable.map((g) => <Cell key={g.group} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <p className="pt-2 text-xs text-ink-500 dark:text-ink-400">{data.direction}</p>
          </>
        )}
      </Panel>

      {/* ── like for like ──────────────────────────────────────────── */}
      <Panel
        title={`Like for like, by ${data.group_by_label.toLowerCase()}`}
        description={`The comparison that speaks to equal pay for similar work. ${comparable.length} of ${data.like_for_like.length} groups have at least ${data.min_group_size} of each gender and can be compared.`}
      >
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-ink-200 text-[10px] uppercase tracking-wide text-ink-400 dark:border-white/10">
                <th className="py-2 text-left font-semibold">{data.group_by_label}</th>
                <th className="py-2 text-right font-semibold">Women</th>
                <th className="py-2 text-right font-semibold">Men</th>
                <th className="py-2 text-right font-semibold">Women median</th>
                <th className="py-2 text-right font-semibold">Men median</th>
                <th className="py-2 text-right font-semibold">Median gap</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {data.like_for_like.map((group) => {
                const gap = describeGap(group.median_gap_pct);
                return (
                  <tr
                    key={group.group}
                    onClick={() => onSelectGroup?.(group.group)}
                    className={cn(
                      "border-b border-ink-100 last:border-0 dark:border-white/5",
                      !group.comparable && "text-ink-400 dark:text-ink-500",
                      onSelectGroup && "cursor-pointer hover:bg-ink-50 dark:hover:bg-white/[0.04]",
                    )}
                  >
                    <td className="py-2 pr-3 text-ink-800 dark:text-ink-100">{group.group}</td>
                    <td className="py-2 text-right">{group.women.count}</td>
                    <td className="py-2 text-right">{group.men.count}</td>
                    <td className="py-2 text-right">
                      {group.women.median === null ? withheld() : formatINR(group.women.median, true)}
                    </td>
                    <td className="py-2 text-right">
                      {group.men.median === null ? withheld() : formatINR(group.men.median, true)}
                    </td>
                    <td className={cn("py-2 text-right font-medium", toneClass(gap.tone))}>
                      {group.comparable ? gap.text : withheld()}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {data.suppressed_groups.length > 0 && (
          <p className="mt-3 flex items-start gap-2 rounded-lg border border-ink-200/70 bg-ink-50 px-3 py-2 text-xs text-ink-600 dark:border-white/10 dark:bg-white/[0.03] dark:text-ink-400">
            <EyeOff size={14} className="mt-px flex-shrink-0" />
            <span>
              {data.suppressed_groups.length} group
              {data.suppressed_groups.length === 1 ? " is" : "s are"} withheld — fewer than{" "}
              {data.min_group_size} employees of one gender, where a median would disclose
              individual pay. They are listed above with their counts so you can see what was
              held back rather than assuming it was absent.
            </span>
          </p>
        )}
      </Panel>

      {/* ── what this is not ───────────────────────────────────────── */}
      <Panel title="How to read this" description="Every figure above, and what none of them says.">
        <ul className="max-w-[72ch] list-disc space-y-2 pl-5 text-sm text-ink-600 dark:text-ink-300">
          {data.caveats.map((caveat) => <li key={caveat}>{caveat}</li>)}
        </ul>
        <p className="mt-3 flex items-start gap-2 text-xs text-ink-500 dark:text-ink-400">
          <Users size={13} className="mt-px flex-shrink-0" />
          <span>
            No individual appears anywhere in this view or its export, at any permission level.
            Every view is written to the audit trail.
          </span>
        </p>
      </Panel>
    </div>
  );
}

function withheld() {
  return <span className="text-[11px] uppercase tracking-wide text-ink-400">withheld</span>;
}

function GapTile({
  label, gap, detail,
}: {
  label: string;
  gap: { text: string; tone: string };
  detail: string;
}) {
  return (
    <div className="rounded-xl border border-ink-200/70 px-3.5 py-3 dark:border-white/10">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">{label}</p>
      <p className={cn("font-display text-2xl font-semibold tabular-nums", toneClass(gap.tone))}>
        {gap.text}
      </p>
      <p className="text-[11px] text-ink-500 dark:text-ink-400">
        {gap.tone === "gap" ? "Women paid less. " : gap.tone === "reverse" ? "Women paid more. " : ""}
        {detail}
      </p>
    </div>
  );
}

function GenderCard({
  label, summary, palette,
}: {
  label: string;
  summary?: GenderSummary;
  palette: string;
}) {
  return (
    <div className="rounded-xl border border-ink-200/70 px-3.5 py-3 dark:border-white/10">
      <p className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
        <span aria-hidden className="h-2.5 w-2.5 rounded-full" style={{ background: palette }} />
        {label}
      </p>
      {!summary ? (
        <p className="text-sm text-ink-400">—</p>
      ) : summary.suppressed ? (
        <>
          <p className="font-display text-xl font-semibold text-ink-400">Withheld</p>
          <p className="text-[11px] text-ink-500 dark:text-ink-400">
            {summary.count} employee{summary.count === 1 ? "" : "s"} — too few to report a median
            without disclosing pay
          </p>
        </>
      ) : (
        <>
          <p className="font-display text-xl font-semibold tabular-nums text-ink-900 dark:text-white">
            {formatINR(summary.median ?? 0, true)}
          </p>
          <p className="text-[11px] text-ink-500 dark:text-ink-400">
            median · {summary.count} employees · mean {formatINR(summary.mean ?? 0, true)}
            {summary.variable_receipt_pct !== null && (
              <> · {summary.variable_receipt_pct.toFixed(0)}% receive variable pay</>
            )}
          </p>
        </>
      )}
    </div>
  );
}

function GapTooltip({
  active,
  payload,
  chrome,
}: {
  active?: boolean;
  payload?: { payload: { name: string; gap: number } }[];
  chrome: ReturnType<typeof chartTheme>;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  const gap = describeGap(row.gap);
  return (
    <div
      className="rounded-lg border px-3 py-2 text-xs shadow-lg"
      style={{ background: chrome.surface, borderColor: chrome.border, color: chrome.ink }}
    >
      <p className="font-semibold">{row.name}</p>
      <p className="pt-0.5">
        Women paid <span className="font-semibold">{gap.text}</span> at the median
      </p>
    </div>
  );
}
