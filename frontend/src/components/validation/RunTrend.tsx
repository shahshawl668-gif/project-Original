"use client";

/**
 * The months this company has checked, side by side: open critical findings
 * and warnings from each month's current run. Drawn from the runs list, so a
 * column is exactly the figures the month's own results page shows.
 */
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { Columns, Legend, PASSED_COLOR, Panel, SEVERITY_COLOR } from "@/components/viz/charts";
import { useEntity } from "@/context/EntityContext";
import { count, plural } from "@/lib/format";
import { validationApi } from "@/lib/validation";
import { normalisePeriod, periodLabel } from "@/lib/workspace";

const SHOWN = 18;

export function RunTrend() {
  const router = useRouter();
  const { entity } = useEntity();
  const q = useQuery({
    queryKey: ["run-periods", entity?.id],
    queryFn: () => validationApi.runs({ limit: 200 }),
    enabled: !!entity,
    staleTime: 60_000,
  });
  const months = (q.data ?? [])
    .filter((r) => r.status === "current" && normalisePeriod(r.period_month))
    .sort((a, b) => a.period_month.localeCompare(b.period_month));
  if (months.length < 2) return null;
  const drawn = months.slice(-SHOWN);
  const first = drawn[0], last = drawn[drawn.length - 1];
  const open = (r: { critical_count: number; warning_count: number }) => r.critical_count + r.warning_count;
  const change = open(last) - open(first);
  return (
    <Panel
      title="Month by month"
      sub={<>Open critical findings and warnings in each month&apos;s current run, after waivers.{" "}
        {change === 0 ? "No change" : `${change < 0 ? "Down" : "Up"} ${count(Math.abs(change))}`} from {periodLabel(normalisePeriod(first.period_month))} to {periodLabel(normalisePeriod(last.period_month))}.
        {months.length > SHOWN ? ` The latest ${SHOWN} of ${plural(months.length, "month")} are drawn.` : ""}</>}
    >
      <div className="overflow-x-auto">
        <div style={{ minWidth: `${drawn.length * 3.25}rem`, maxWidth: `${drawn.length * 6}rem` }}>
          <Columns
            caption="Open critical findings and warnings by month"
            zero={PASSED_COLOR}
            zeroWord="no open critical finding or warning"
            columns={drawn.map((r) => ({
              key: r.id, label: periodLabel(normalisePeriod(r.period_month)).replace(/ 20(\d\d)$/, " ’$1"),
              onClick: () => router.push(`/payroll/results?run=${encodeURIComponent(r.id)}`),
              parts: [
                { label: "Critical", value: r.critical_count, color: SEVERITY_COLOR.CRITICAL },
                { label: "Warning", value: r.warning_count, color: SEVERITY_COLOR.WARNING },
              ],
            }))}
          />
        </div>
      </div>
      <Legend className="mt-2" items={[
        { label: "Critical, open", color: SEVERITY_COLOR.CRITICAL },
        { label: "Warnings, open", color: SEVERITY_COLOR.WARNING },
        { label: "None open", color: PASSED_COLOR },
      ]} />
    </Panel>
  );
}
