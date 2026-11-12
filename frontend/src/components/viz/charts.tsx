"use client";

/**
 * The product's pictures.
 *
 * Every chart here draws counts it is handed and nothing else: no smoothing,
 * no estimated values, no scale that starts anywhere but zero. Each one states
 * its figures in words as well — a label and a number beside every mark, and
 * a description for a screen reader — so colour never carries the meaning
 * alone and the picture can always be checked against the table under it.
 *
 * Marks are plain SVG and CSS. Severity uses the status colours, which mean
 * the same thing everywhere in the product.
 */
import { useId, useState, type ReactNode } from "react";

import { count, pct } from "@/lib/format";
import { cn } from "@/lib/utils";

export const SEVERITY_COLOR = { CRITICAL: "#d03b3b", WARNING: "#fab219", INFO: "#2a78d6" } as const;
export const SEVERITY_NAME = { CRITICAL: "Critical", WARNING: "Warning", INFO: "Info" } as const;
export type Severity = keyof typeof SEVERITY_COLOR;
export const SEVERITIES: Severity[] = ["CRITICAL", "WARNING", "INFO"];
export const PASSED_COLOR = "#0ca30c";
const TRACK = "#eef0f3";

export function Panel({ title, sub, action, children, className }: {
  title: string; sub?: ReactNode; action?: ReactNode; children: ReactNode; className?: string;
}) {
  const id = useId();
  return (
    <section aria-labelledby={id} className={cn("rounded-xl border border-ink-200 bg-white p-4 shadow-soft", className)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 id={id} className="text-[13px] font-semibold text-ink-900">{title}</h3>
          {sub ? <p className="text-xs text-ink-500">{sub}</p> : null}
        </div>
        {action}
      </div>
      <div className="mt-3">{children}</div>
    </section>
  );
}

export function Legend({ items, className }: { items: { label: string; color: string; value?: ReactNode }[]; className?: string }) {
  return (
    <ul className={cn("flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-600", className)}>
      {items.map((i) => (
        <li key={i.label} className="flex items-center gap-1.5">
          <span className="h-2 w-2 flex-shrink-0 rounded-sm" style={{ background: i.color }} aria-hidden />
          {i.label}
          {i.value !== undefined ? <span className="num font-medium text-ink-900">{i.value}</span> : null}
        </li>
      ))}
    </ul>
  );
}

/** A floating label for the mark under the pointer. */
function Tip({ children }: { children: ReactNode }) {
  return (
    <div role="status" className="pointer-events-none absolute left-1/2 top-0 z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-lg border border-ink-200 bg-white px-2.5 py-1.5 text-xs text-ink-800 shadow-elevated">
      {children}
    </div>
  );
}

// ─── Donut ───────────────────────────────────────────────────────────────────

export type Slice = { label: string; value: number; color: string };

/**
 * Parts of a whole. Slices are drawn in the order given, clockwise from the
 * top, each exactly its share of the total; the total sits in the middle.
 */
export function Donut({ slices, total, centre, caption, size = 148 }: {
  slices: Slice[]; total: number; centre: ReactNode; caption: string; size?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const r = 54, c = 2 * Math.PI * r, gap = slices.filter((s) => s.value > 0).length > 1 ? 2 : 0;
  let offset = 0;
  const shown = hover === null ? null : slices[hover];
  return (
    <div className="flex flex-wrap items-center gap-5">
      <div className="relative flex-shrink-0" style={{ width: size, height: size }}>
        <svg viewBox="0 0 140 140" role="img" className="h-full w-full -rotate-90"
             aria-label={`${caption}: ${slices.map((s) => `${s.label} ${count(s.value)}`).join(", ")}. Total ${count(total)}.`}>
          <circle cx="70" cy="70" r={r} fill="none" stroke={TRACK} strokeWidth="14" />
          {total > 0 && slices.map((s, i) => {
            const len = (s.value / total) * c;
            const dash = Math.max(0, len - gap);
            const el = s.value > 0 ? (
              <circle key={s.label} cx="70" cy="70" r={r} fill="none" stroke={s.color}
                      strokeWidth={hover === i ? 18 : 14} strokeDasharray={`${dash} ${c - dash}`} strokeDashoffset={-offset}
                      className="transition-[stroke-width] duration-150"
                      onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
            ) : null;
            offset += len;
            return el;
          })}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
          {shown ? (
            <>
              <span className="num text-2xl font-semibold tracking-tight text-ink-900">{count(shown.value)}</span>
              <span className="text-2xs text-ink-500">{shown.label} · {pct(total ? (shown.value / total) * 100 : 0)}</span>
            </>
          ) : centre}
        </div>
      </div>
      <ul className="min-w-[9rem] flex-1 space-y-1.5">
        {slices.map((s, i) => (
          <li key={s.label} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
              className={cn("flex items-center justify-between gap-3 rounded-md px-1.5 py-0.5 text-xs", hover === i && "bg-ink-50")}>
            <span className="flex items-center gap-1.5 text-ink-600">
              <span className="h-2 w-2 rounded-sm" style={{ background: s.color }} aria-hidden />{s.label}
            </span>
            <span className="num text-ink-900">
              <span className="font-semibold">{count(s.value)}</span>
              <span className="ml-1.5 text-ink-500">{pct(total ? (s.value / total) * 100 : 0)}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ─── Ring gauge ──────────────────────────────────────────────────────────────

/** One percentage, as an arc from the top. `value` is 0–100; null draws an empty ring. */
export function Ring({ value, color = PASSED_COLOR, label, size = 112, children }: {
  value: number | null; color?: string; label: string; size?: number; children: ReactNode;
}) {
  const r = 46, c = 2 * Math.PI * r;
  const share = value === null ? 0 : Math.min(100, Math.max(0, value)) / 100;
  return (
    <div className="relative flex-shrink-0" style={{ width: size, height: size }}>
      <svg viewBox="0 0 112 112" role="img" aria-label={label} className="h-full w-full -rotate-90">
        <circle cx="56" cy="56" r={r} fill="none" stroke={TRACK} strokeWidth="10" />
        {share > 0 ? (
          <circle cx="56" cy="56" r={r} fill="none" stroke={color} strokeWidth="10" strokeLinecap="round"
                  strokeDasharray={`${share * c} ${c}`} />
        ) : null}
      </svg>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">{children}</div>
    </div>
  );
}

// ─── Stacked bars ────────────────────────────────────────────────────────────

export type BarRow = {
  key: string; label: string; parts: { label: string; value: number; color: string }[];
  /** Shown to the right of the bar; defaults to the sum of the parts. */
  note?: ReactNode; onClick?: () => void;
};

/**
 * One horizontal bar per row, all on the same scale from zero: a bar twice as
 * long is twice the count. Parts sit side by side with a gap between them.
 */
export function StackedBars({ rows, caption, max }: { rows: BarRow[]; caption: string; max?: number }) {
  const [hover, setHover] = useState<string | null>(null);
  const totals = rows.map((r) => r.parts.reduce((a, p) => a + p.value, 0));
  const scale = Math.max(1, max ?? 0, ...totals);
  return (
    <ul className="space-y-2" aria-label={caption}>
      {rows.map((row, i) => {
        const body = (
          <>
            <div className="flex items-baseline justify-between gap-3 text-xs">
              <span className="truncate text-ink-700 group-hover:text-ink-900">{row.label}</span>
              <span className="num flex-shrink-0 font-medium text-ink-900">{row.note ?? count(totals[i])}</span>
            </div>
            <div className="relative mt-1">
              <div className="flex h-2.5 gap-0.5 overflow-hidden rounded-full bg-ink-100">
                {row.parts.map((p) => p.value > 0 ? (
                  <div key={p.label} style={{ width: `${(p.value / scale) * 100}%`, background: p.color }} className="h-full min-w-[3px] first:rounded-l-full" />
                ) : null)}
              </div>
              {hover === row.key ? (
                <Tip>{row.parts.filter((p) => p.value > 0).map((p) => `${p.label} ${count(p.value)}`).join(" · ") || "None"}</Tip>
              ) : null}
            </div>
          </>
        );
        return (
          <li key={row.key} onMouseEnter={() => setHover(row.key)} onMouseLeave={() => setHover(null)}>
            {row.onClick ? (
              <button type="button" onClick={row.onClick} className="group w-full text-left"
                      aria-label={`${row.label}: ${row.parts.map((p) => `${p.label} ${count(p.value)}`).join(", ")}. Show them`}>{body}</button>
            ) : <div className="group">{body}</div>}
          </li>
        );
      })}
    </ul>
  );
}

// ─── Columns ─────────────────────────────────────────────────────────────────

export type Column = { key: string; label: string; parts: { label: string; value: number; color: string }[]; empty?: string; selected?: boolean; onClick?: () => void };

/**
 * One stacked column per slot, on one scale from zero. A slot with nothing to
 * draw says why (`empty`) instead of showing a zero-height bar that reads as
 * "nothing found".
 */
export function Columns({ columns, caption, height = 96, zero = "#dfe2e8", zeroWord = "none" }: {
  columns: Column[]; caption: string; height?: number;
  /** Colour and wording of a slot whose total is zero. */
  zero?: string; zeroWord?: string;
}) {
  const [hover, setHover] = useState<string | null>(null);
  const totals = columns.map((c) => c.parts.reduce((a, p) => a + p.value, 0));
  const scale = Math.max(1, ...totals);
  return (
    <div role="group" aria-label={caption} className="grid gap-1.5" style={{ gridTemplateColumns: `repeat(${columns.length}, minmax(0, 1fr))` }}>
      {columns.map((col, i) => {
        const total = totals[i];
        const inner = (
          <>
            <div className="relative flex w-full items-end justify-center" style={{ height }}>
              {col.empty !== undefined ? (
                <span className="mb-1 text-2xs text-ink-400">{col.empty}</span>
              ) : (
                <div className="flex w-full max-w-[28px] flex-col-reverse gap-0.5">
                  {total === 0 ? <div className="h-[3px] rounded-sm" style={{ background: zero }} /> : col.parts.map((p) => p.value > 0 ? (
                    <div key={p.label} className="rounded-sm" style={{ height: Math.max(3, (p.value / scale) * (height - 18)), background: p.color }} />
                  ) : null)}
                </div>
              )}
              {col.empty === undefined ? <span className="num absolute -top-0.5 text-2xs font-medium text-ink-700">{count(total)}</span> : null}
              {hover === col.key && col.empty === undefined ? (
                <Tip>{col.label}: {total === 0 ? zeroWord : col.parts.filter((p) => p.value > 0).map((p) => `${p.label} ${count(p.value)}`).join(" · ")}</Tip>
              ) : null}
            </div>
            <span className={cn("mt-1 block text-center text-2xs", col.selected ? "font-semibold text-brand-700" : "text-ink-500")}>{col.label}</span>
            <span className={cn("mx-auto mt-0.5 block h-0.5 w-6 rounded-full", col.selected ? "bg-brand-600" : "bg-transparent")} aria-hidden />
          </>
        );
        const label = `${col.label}: ${col.empty ?? (total === 0 ? zeroWord : col.parts.map((p) => `${p.label} ${count(p.value)}`).join(", "))}`;
        return col.onClick ? (
          <button key={col.key} type="button" onClick={col.onClick} aria-label={label} aria-pressed={col.selected}
                  onMouseEnter={() => setHover(col.key)} onMouseLeave={() => setHover(null)}
                  className="rounded-lg px-0.5 pt-2 transition-colors hover:bg-ink-50">{inner}</button>
        ) : (
          <div key={col.key} aria-label={label} onMouseEnter={() => setHover(col.key)} onMouseLeave={() => setHover(null)} className="px-0.5 pt-2">{inner}</div>
        );
      })}
    </div>
  );
}

// ─── Heat grid ───────────────────────────────────────────────────────────────

export type GridCell = Partial<Record<Severity, number>>;
export type GridRow = { key: string; label: string; sub?: string; cells: Record<string, GridCell>; onClick?: () => void };

function worst(cell: GridCell | undefined): Severity | null {
  if (!cell) return null;
  return SEVERITIES.find((s) => (cell[s] ?? 0) > 0) ?? null;
}

/**
 * Who failed what. A cell is coloured by its worst finding and carries the
 * number of findings in it; an empty cell is a dot, not a zero, because "no
 * finding" is not the same claim as "checked and passed".
 */
export function HeatGrid({ columns, rows, caption }: { columns: { key: string; label: string }[]; rows: GridRow[]; caption: string }) {
  const [hover, setHover] = useState<string | null>(null);
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate border-spacing-[3px] text-xs">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            <th scope="col" className="sticky left-0 bg-white text-left font-medium text-ink-500">Employee</th>
            {columns.map((c) => (
              <th key={c.key} scope="col" className="min-w-[4.5rem] px-1 pb-1 text-center align-bottom text-2xs font-medium leading-tight text-ink-500">{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className="group">
              <th scope="row" className="sticky left-0 max-w-[13rem] bg-white pr-3 text-left font-normal">
                {row.onClick ? (
                  <button type="button" onClick={row.onClick} className="block w-full truncate text-left text-ink-800 hover:text-brand-700 hover:underline">
                    {row.label}{row.sub ? <span className="ml-1.5 font-mono text-2xs text-ink-500">{row.sub}</span> : null}
                  </button>
                ) : <span className="block truncate text-ink-800">{row.label}</span>}
              </th>
              {columns.map((c) => {
                const cell = row.cells[c.key];
                const w = worst(cell);
                const n = cell ? SEVERITIES.reduce((a, s) => a + (cell[s] ?? 0), 0) : 0;
                const id = `${row.key}:${c.key}`;
                const words = w ? SEVERITIES.filter((s) => (cell?.[s] ?? 0) > 0).map((s) => `${SEVERITY_NAME[s]} ${cell![s]}`).join(", ") : "no finding";
                return (
                  <td key={c.key} className="relative p-0" onMouseEnter={() => setHover(id)} onMouseLeave={() => setHover(null)}>
                    <div aria-label={`${row.label}, ${c.label}: ${words}`}
                         className={cn("num flex h-7 items-center justify-center rounded-md text-xs font-semibold", !w && "bg-ink-50 text-ink-300")}
                         style={w ? { background: SEVERITY_COLOR[w], color: w === "WARNING" ? "#1f2533" : "#ffffff" } : undefined}>
                      {w ? n : "·"}
                    </div>
                    {hover === id && w ? <Tip>{row.label} · {c.label}: {words}</Tip> : null}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
