"use client";

/**
 * A run, drawn: how serious, where in payroll, who, and how the risk is
 * spread. Every figure comes from the run-picture endpoint, which counts the
 * whole run in the database, so these charts and the tables below them cannot
 * disagree.
 */
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { Columns, Donut, HeatGrid, Legend, Panel, SEVERITIES, SEVERITY_COLOR, SEVERITY_NAME, StackedBars } from "@/components/viz/charts";
import { CHART } from "@/lib/chart-colors";
import { count, pct, plural } from "@/lib/format";
import { validationApi, type RunPicture as Picture } from "@/lib/validation";

function Groups({ title, noun, group, employees }: { title: string; noun: string; group: Picture["departments"]; employees: number }) {
  const recorded = group.items.length > 0;
  return (
    <Panel title={title} sub={`Employees with at least one finding, out of everyone in the ${noun}`}>
      {!recorded ? (
        <p className="text-xs text-ink-500">
          No {noun} is recorded for the {plural(employees, "employee")} in this run, so there is nothing to split by.
          Add it to the employee master to see this.
        </p>
      ) : (
        <>
          <StackedBars
            caption={title}
            max={Math.max(...group.items.map((g) => g.employees))}
            rows={group.items.map((g) => ({
              key: g.name, label: g.name,
              parts: [
                { label: "With findings", value: g.with_findings, color: "#fab219" },
                { label: "Clean", value: g.employees - g.with_findings, color: "#0ca30c" },
              ],
              note: <>{count(g.with_findings)} of {count(g.employees)} <span className="text-ink-500">· {pct((g.with_findings / g.employees) * 100)}</span></>,
            }))}
          />
          <Legend className="mt-3" items={[{ label: "With findings", color: "#fab219" }, { label: "Clean", color: "#0ca30c" }]} />
          {group.not_shown || group.unassigned.employees ? (
            <p className="mt-2 text-2xs text-ink-500">
              {group.not_shown ? `${plural(group.not_shown, `more ${noun}`)} not drawn. ` : ""}
              {group.unassigned.employees ? `${plural(group.unassigned.employees, "employee")} with no ${noun} recorded (${count(group.unassigned.with_findings)} with findings).` : ""}
            </p>
          ) : null}
        </>
      )}
    </Panel>
  );
}

export function RunPicture({ runId, onSeverity }: { runId: string; onSeverity?: (severity: string) => void }) {
  const router = useRouter();
  const q = useQuery({ queryKey: ["run-picture", runId], queryFn: () => validationApi.picture(runId) });
  const p = q.data;

  if (q.isError) {
    return <p className="rounded-xl border border-ink-200 bg-white p-4 text-xs text-ink-500">The charts for this run could not be loaded. The tables below are unaffected.</p>;
  }
  if (!p) return <div className="h-48 animate-pulse rounded-xl border border-ink-200 bg-white" aria-busy="true" aria-label="Loading charts" />;

  if (p.findings === 0) {
    return (
      <Panel title="Run picture" sub="Findings recorded in this run">
        <p className="text-xs text-ink-600">No check failed for any of the {plural(p.employees, "employee")} in this run. Which checks ran, and which could not, is on the Coverage tab.</p>
      </Panel>
    );
  }

  const more = p.matrix.employees_with_findings - p.matrix.shown;
  return (
    <div className="space-y-4">
      <div className="grid items-start gap-4 lg:grid-cols-[2fr_3fr]">
        <Panel title="Findings by severity" sub="Every finding this run recorded, before any waiver">
          <Donut
            caption="Findings by severity"
            total={p.findings}
            slices={SEVERITIES.map((s) => ({ label: SEVERITY_NAME[s], value: p.severity[s], color: SEVERITY_COLOR[s] }))}
            centre={<><span className="num text-2xl font-semibold tracking-tight text-ink-900">{count(p.findings)}</span><span className="text-2xs text-ink-500">findings</span></>}
          />
          {onSeverity ? (
            <p className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs">
              {SEVERITIES.filter((s) => p.severity[s] > 0).map((s) => (
                <button key={s} type="button" onClick={() => onSeverity(s)} className="font-medium text-brand-700 hover:underline">
                  Show {SEVERITY_NAME[s].toLowerCase()}
                </button>
              ))}
            </p>
          ) : null}
        </Panel>

        <Panel title="Where in payroll" sub="Findings by area, split by severity · employees affected on the right">
          <StackedBars
            caption="Findings by area of payroll"
            rows={p.areas.map((a) => ({
              key: a.area, label: a.label,
              parts: SEVERITIES.map((s) => ({ label: SEVERITY_NAME[s], value: a[s], color: SEVERITY_COLOR[s] })),
              note: <>{count(a.findings)} <span className="font-normal text-ink-500">· {plural(a.employees, "employee")}</span></>,
            }))}
          />
          <Legend className="mt-3" items={SEVERITIES.map((s) => ({ label: SEVERITY_NAME[s], color: SEVERITY_COLOR[s] }))} />
        </Panel>
      </div>

      <Panel
        title="Who failed what"
        sub={<>Each cell is one employee in one area, coloured by its worst finding, with the number of findings in it. {more > 0
          ? `The ${count(p.matrix.shown)} highest-risk of ${count(p.matrix.employees_with_findings)} employees with findings are drawn.`
          : `All ${count(p.matrix.shown)} employees with findings are drawn, highest risk first.`}</>}
        action={<Legend items={[...SEVERITIES.map((s) => ({ label: SEVERITY_NAME[s], color: SEVERITY_COLOR[s] })), { label: "No finding", color: "#eef0f3" }]} />}
      >
        <HeatGrid
          caption="Findings per employee and area of payroll"
          columns={p.matrix.areas.map((a) => ({ key: a.area, label: a.label }))}
          rows={p.matrix.rows.map((r) => ({
            key: r.employee_id, label: r.employee_name || r.employee_id, sub: r.employee_name ? r.employee_id : undefined,
            cells: r.cells,
            onClick: () => router.push(`/payroll/employee/${encodeURIComponent(r.employee_id)}?run=${encodeURIComponent(runId)}`),
          }))}
        />
      </Panel>

      <div className="grid items-start gap-4 lg:grid-cols-3">
        <Panel title="Risk spread" sub={`Employees by risk score, in bands of ${p.risk.bucket} · medium from 25, high from 60`}>
          <Columns
            caption="Employees by risk score"
            columns={p.risk.buckets.map((b) => ({
              key: String(b.from), label: `${b.from}–${b.to}`,
              parts: [{ label: "Employees", value: b.employees, color: CHART.primary }],
            }))}
          />
        </Panel>
        <Groups title="By work state" noun="state" group={p.locations} employees={p.employees} />
        <Groups title="By department" noun="department" group={p.departments} employees={p.employees} />
      </div>
    </div>
  );
}
