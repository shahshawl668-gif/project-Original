"use client";

import { forwardRef, useMemo, type SelectHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

/** The financial years offered: April to March, named by the year they start in. */
const FIRST_FY = 2025;
const LAST_FY = 2027;

const label = (p: string) =>
  new Date(`${p}-01T00:00:00`).toLocaleDateString("en-IN", { month: "short", year: "numeric" }).replace("Sept", "Sep");

function fyMonths(start: number): string[] {
  return Array.from({ length: 12 }, (_, i) => {
    const m = ((3 + i) % 12) + 1;
    return `${m >= 4 ? start : start + 1}-${String(m).padStart(2, "0")}`;
  });
}

const fyOf = (p: string) => {
  const [y, m] = p.split("-").map(Number);
  return m >= 4 ? y : y - 1;
};

type Props = Omit<SelectHTMLAttributes<HTMLSelectElement>, "value" | "onChange"> & {
  /** "YYYY-MM", or "" for none chosen. */
  value: string;
  onChange: (value: string) => void;
  /** Shown as the first, empty choice; leave out to require a month. */
  placeholder?: string;
};

/**
 * A payroll month chosen from a list, never typed: months grouped by financial
 * year (April to March), FY 2025-26 to FY 2027-28, plus the current value if it
 * falls outside them.
 */
export const MonthSelect = forwardRef<HTMLSelectElement, Props>(function MonthSelect(
  { value, onChange, placeholder, className, ...rest },
  ref,
) {
  const years = useMemo(() => {
    const out = new Set<number>();
    for (let y = FIRST_FY; y <= LAST_FY; y += 1) out.add(y);
    if (/^\d{4}-\d{2}$/.test(value)) out.add(fyOf(value));
    return [...out].sort((a, b) => b - a);
  }, [value]);

  return (
    <select
      ref={ref}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={cn(
        "h-9 min-w-[10rem] rounded-lg border border-ink-200 bg-white px-2.5 text-[13px] text-ink-900 shadow-soft focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20",
        className,
      )}
      {...rest}
    >
      {placeholder !== undefined || !value ? <option value="">{placeholder ?? "Choose a month"}</option> : null}
      {years.map((y) => (
        <optgroup key={y} label={`FY ${y}-${String((y + 1) % 100).padStart(2, "0")}`}>
          {fyMonths(y).reverse().map((m) => (
            <option key={m} value={m}>{label(m)}</option>
          ))}
        </optgroup>
      ))}
    </select>
  );
});
