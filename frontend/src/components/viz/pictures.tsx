"use client";

/**
 * The employee master, a month of attendance and the audit trail, drawn.
 *
 * Each reads a picture endpoint that counts every row on the server, and each
 * says what it could not draw: a field nobody recorded is "not recorded", and
 * a column the file never carried has no total rather than a zero.
 */
import { useQuery } from "@tanstack/react-query";

import { Columns, Donut, Legend, PASSED_COLOR, Panel, StackedBars } from "@/components/viz/charts";
import { apiJson } from "@/lib/api";
import { CHART } from "@/lib/chart-colors";
import { SERIES } from "@/lib/cost-analysis";
import { count, pct, plural } from "@/lib/format";

type Group = { items: { name: string; employees: number }[]; not_shown: number; not_shown_employees: number; not_recorded: number };
type MasterPictureData = {
  as_of: string; employees: number; active: number; left: number;
  by_state: Group; by_department: Group; by_gender: Group; by_employment_type: Group;
  joined_by_year: { items: { year: number; employees: number }[]; not_recorded: number };
  fields: { field: string; label: string; recorded: number }[];
};

const NOT_RECORDED = "#b7bdc9";

function GroupBars({ title, noun, group, total }: { title: string; noun: string; group: Group; total: number }) {
  return (
    <Panel title={title} sub={`Employees by ${noun}`}>
      {group.items.length === 0 ? (
        <p className="text-xs text-ink-500">No {noun} is recorded for any of the {plural(total, "employee")}.</p>
      ) : (
        <StackedBars
          caption={title}
          rows={group.items.map((g) => ({
            key: g.name, label: g.name,
            parts: [{ label: "Employees", value: g.employees, color: CHART.primary }],
            note: <>{count(g.employees)} <span className="font-normal text-ink-500">· {pct((g.employees / total) * 100)}</span></>,
          }))}
        />
      )}
      {group.not_recorded || group.not_shown ? (
        <p className="mt-2 text-2xs text-ink-500">
          {group.not_recorded ? `${plural(group.not_recorded, "employee")} with no ${noun} recorded. ` : ""}
          {group.not_shown ? `${plural(group.not_shown, "more group")} (${plural(group.not_shown_employees, "employee")}) not drawn.` : ""}
        </p>
      ) : null}
    </Panel>
  );
}

export function MasterPicture() {
  const q = useQuery({ queryKey: ["master-uploads", "picture"], queryFn: () => apiJson<MasterPictureData>("/api/workforce/master/picture") });
  const p = q.data;
  if (!p || p.employees === 0) return null;
  const genders = p.by_gender.items;
  return (
    <div className="space-y-4">
      <div className="grid items-start gap-4 lg:grid-cols-3">
        <Panel title="Who is on the master" sub={`As it stands today · ${plural(p.employees, "employee")}`}>
          <Donut
            caption="Employees by whether they have left"
            total={p.employees}
            size={132}
            slices={[
              { label: "Working", value: p.active, color: PASSED_COLOR },
              { label: "Left", value: p.left, color: NOT_RECORDED },
            ]}
            centre={<><span className="num text-xl font-semibold tracking-tight text-ink-900">{count(p.employees)}</span><span className="text-2xs text-ink-500">on the master</span></>}
          />
        </Panel>
        <Panel title="Gender" sub="As recorded on the master">
          <Donut
            caption="Employees by gender"
            total={p.employees}
            size={132}
            slices={[
              ...genders.map((g, i) => ({ label: g.name, value: g.employees, color: SERIES[i % SERIES.length] })),
              ...(p.by_gender.not_recorded ? [{ label: "Not recorded", value: p.by_gender.not_recorded, color: NOT_RECORDED }] : []),
            ]}
            centre={<><span className="num text-xl font-semibold tracking-tight text-ink-900">{count(p.employees - p.by_gender.not_recorded)}</span><span className="text-2xs text-ink-500">recorded</span></>}
          />
        </Panel>
        <Panel title="What is filled in" sub="Employees with each field recorded · an empty field switches off the checks that read it">
          <StackedBars
            caption="Master fields recorded"
            max={p.employees}
            rows={p.fields.map((f) => ({
              key: f.field, label: f.label,
              parts: [
                { label: "Recorded", value: f.recorded, color: PASSED_COLOR },
                { label: "Missing", value: p.employees - f.recorded, color: "#fab219" },
              ],
              note: <>{count(f.recorded)} <span className="font-normal text-ink-500">of {count(p.employees)}</span></>,
            }))}
          />
          <Legend className="mt-3" items={[{ label: "Recorded", color: PASSED_COLOR }, { label: "Missing", color: "#fab219" }]} />
        </Panel>
      </div>
      <div className="grid items-start gap-4 lg:grid-cols-3">
        <GroupBars title="By work state" noun="work state" group={p.by_state} total={p.employees} />
        <GroupBars title="By department" noun="department" group={p.by_department} total={p.employees} />
        <Panel title="Joined, by year" sub={`From the date of joining${p.joined_by_year.not_recorded ? ` · ${plural(p.joined_by_year.not_recorded, "employee")} with none recorded` : ""}`}>
          {p.joined_by_year.items.length ? (
            <div className="overflow-x-auto">
              <div style={{ minWidth: `${p.joined_by_year.items.length * 2.75}rem` }}>
                <Columns
                  caption="Employees by year of joining"
                  columns={p.joined_by_year.items.map((y) => ({
                    key: String(y.year), label: String(y.year),
                    parts: [{ label: "Joined", value: y.employees, color: CHART.primary }],
                  }))}
                />
              </div>
            </div>
          ) : <p className="text-xs text-ink-500">No date of joining is recorded.</p>}
        </Panel>
      </div>
    </div>
  );
}

// ─── Attendance ──────────────────────────────────────────────────────────────

type Stated = { total: number | null; employees_stated: number };
type AttendancePictureData = {
  register_id: string; period_month: string; employees: number;
  days: Record<"present_days" | "paid_days" | "lop_days" | "paid_leave_days" | "weekly_off_days" | "holiday_days", Stated>;
  overtime_hours: Stated; with_overtime: number;
  lop_bands: { items: { label: string; employees: number }[]; not_recorded: number };
};
const DAY_LABEL: Record<string, string> = {
  present_days: "Present", paid_leave_days: "Paid leave", weekly_off_days: "Weekly off", holiday_days: "Holidays", lop_days: "Loss of pay",
};
// Loss of pay is the only kind that is a problem, so it alone is red; days off are neutral.
const DAY_COLOR: Record<string, string> = {
  present_days: PASSED_COLOR, paid_leave_days: SERIES[0], weekly_off_days: "#8a93a4", holiday_days: "#8a93a4", lop_days: "#d03b3b",
};
const days1 = (n: number) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 1 }).format(n);

export function AttendancePicture({ registerId, label }: { registerId: string; label: string }) {
  const q = useQuery({
    queryKey: ["attendance-registers", "picture", registerId],
    queryFn: () => apiJson<AttendancePictureData>(`/api/workforce/attendance/${encodeURIComponent(registerId)}/picture`),
  });
  const p = q.data;
  if (!p || p.employees === 0) return null;
  const kinds = (Object.keys(DAY_LABEL) as (keyof AttendancePictureData["days"])[]).filter((k) => p.days[k].total !== null);
  const missing = (Object.keys(DAY_LABEL) as (keyof AttendancePictureData["days"])[]).filter((k) => p.days[k].total === null);
  const lop = p.days.lop_days;
  const withLop = p.lop_bands.items.filter((b) => b.label !== "None").reduce((a, b) => a + b.employees, 0);
  return (
    <div className="grid items-start gap-4 lg:grid-cols-3">
      <Panel title={`Days in ${label}`} sub={`Employee-days by kind, added up over ${plural(p.employees, "employee")}`}>
        {kinds.length ? (
          <StackedBars
            caption="Employee-days by kind"
            rows={kinds.map((k) => ({
              key: k, label: DAY_LABEL[k],
              parts: [{ label: "Days", value: p.days[k].total ?? 0, color: DAY_COLOR[k] }],
              note: <>{days1(p.days[k].total ?? 0)} <span className="font-normal text-ink-500">days</span></>,
            }))}
          />
        ) : <p className="text-xs text-ink-500">The file carried no day counts.</p>}
        <p className="mt-2 text-2xs text-ink-500">
          Paid days: {p.days.paid_days.total === null ? "not in the file" : days1(p.days.paid_days.total)}.
          {missing.length ? ` Not in the file: ${missing.map((k) => DAY_LABEL[k].toLowerCase()).join(", ")}.` : ""}
        </p>
      </Panel>
      <Panel title="Loss of pay" sub={lop.total === null ? "The file has no loss-of-pay column" : `${plural(withLop, "employee")} lost pay · ${days1(lop.total)} days in all`}>
        {lop.total === null ? <p className="text-xs text-ink-500">Nothing to draw.</p> : (
          <Columns
            caption="Employees by loss-of-pay days"
            columns={p.lop_bands.items.map((b) => ({
              key: b.label, label: b.label,
              parts: [{ label: "Employees", value: b.employees, color: b.label === "None" ? PASSED_COLOR : "#d03b3b" }],
            }))}
          />
        )}
        {p.lop_bands.not_recorded ? <p className="mt-2 text-2xs text-ink-500">{plural(p.lop_bands.not_recorded, "employee")} with no loss-of-pay figure.</p> : null}
      </Panel>
      <Panel title="Overtime" sub={p.overtime_hours.total === null ? "The file has no overtime column" : "Employees with overtime hours this month"}>
        {p.overtime_hours.total === null ? <p className="text-xs text-ink-500">Nothing to draw.</p> : (
          <Donut
            caption="Employees by whether they worked overtime"
            total={p.employees}
            size={132}
            slices={[
              { label: "With overtime", value: p.with_overtime, color: SERIES[0] },
              { label: "None", value: p.employees - p.with_overtime, color: NOT_RECORDED },
            ]}
            centre={<><span className="num text-xl font-semibold tracking-tight text-ink-900">{days1(p.overtime_hours.total)}</span><span className="text-2xs text-ink-500">hours</span></>}
          />
        )}
      </Panel>
    </div>
  );
}

// ─── Audit trail ─────────────────────────────────────────────────────────────

type AuditPictureData = {
  days: number; from: string; to: string; entries: number; all_time: number;
  by_day: { date: string; entries: number }[];
  by_action: { items: { action: string; entries: number }[]; not_shown: number; not_shown_entries: number };
};

/** "config.bundle_import" → "Config · bundle import", for an action the page has no wording for. */
const humanise = (action: string) => {
  const [head, ...rest] = action.split(".");
  const words = (t: string) => t.replace(/_/g, " ");
  return rest.length ? `${words(head).replace(/^./, (c) => c.toUpperCase())} · ${words(rest.join(" "))}` : words(head);
};

export function AuditPicture({ labels }: { labels: Record<string, string> }) {
  const q = useQuery({ queryKey: ["audit", "picture"], queryFn: () => apiJson<AuditPictureData>("/api/audit/picture?days=30") });
  const p = q.data;
  if (!p || p.all_time === 0) return null;
  const dayLabel = (iso: string, i: number) => {
    const d = new Date(`${iso}T00:00:00`);
    if (i === 0 || d.getDate() === 1) return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
    return d.getDate() % 5 === 0 || i === p.by_day.length - 1 ? String(d.getDate()) : "";
  };
  return (
    <div className="grid items-start gap-4 lg:grid-cols-[3fr_2fr]">
      <Panel title="Activity, last 30 days" sub={`${plural(p.entries, "entry", "entries")} in the last 30 days · ${count(p.all_time)} since the start · days are India time`}>
        <div className="overflow-x-auto">
          <div className="min-w-[40rem]">
            <Columns
              caption="Audit entries per day"
              height={84}
              quietZero
              columns={p.by_day.map((d, i) => ({
                key: d.date, label: dayLabel(d.date, i),
                parts: [{ label: "Entries", value: d.entries, color: CHART.primary }],
              }))}
            />
          </div>
        </div>
      </Panel>
      <Panel title="What was done" sub="Entries by kind, last 30 days">
        {p.by_action.items.length ? (
          <StackedBars
            caption="Audit entries by kind"
            rows={p.by_action.items.map((a) => ({
              key: a.action, label: labels[a.action] ?? humanise(a.action),
              parts: [{ label: "Entries", value: a.entries, color: CHART.primary }],
            }))}
          />
        ) : <p className="text-xs text-ink-500">Nothing in the last 30 days.</p>}
        {p.by_action.not_shown ? <p className="mt-2 text-2xs text-ink-500">{plural(p.by_action.not_shown, "more kind")} ({plural(p.by_action.not_shown_entries, "entry", "entries")}) not drawn.</p> : null}
      </Panel>
    </div>
  );
}
