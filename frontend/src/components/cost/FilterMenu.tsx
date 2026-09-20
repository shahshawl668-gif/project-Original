"use client";

import { useMemo, useState } from "react";
import { Check, Filter, Search, X } from "lucide-react";

import { Menu } from "@/components/cost/Menu";
import type { DimensionMeta } from "@/lib/cost-analysis";
import { cn } from "@/lib/utils";

/**
 * Every dimension filter behind one control.
 *
 * Nine dimensions with a dozen values each is a hundred chips: laid out flat
 * they push the charts off the screen, and they grow with the client's data
 * rather than with anything the designer controls. So the whole set lives here,
 * and what is *selected* comes back out as chips — the only part a reader needs
 * to see without opening anything, because it is the part that changes what the
 * numbers mean.
 */
export function FilterMenu({
  dimensions,
  filters,
  onToggle,
  onClear,
}: {
  dimensions: DimensionMeta[];
  filters: Record<string, string[]>;
  onToggle: (key: string, value: string) => void;
  onClear: () => void;
}) {
  const [search, setSearch] = useState("");
  const count = Object.values(filters).reduce((n, v) => n + v.length, 0);

  // A dimension with one value cannot narrow anything, so offering it is noise.
  const usable = useMemo(
    () => dimensions.filter((d) => d.values.length > 1),
    [dimensions],
  );

  const matching = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return usable;
    return usable
      .map((d) => ({
        ...d,
        values: d.label.toLowerCase().includes(needle)
          ? d.values
          : d.values.filter((v) => v.toLowerCase().includes(needle)),
      }))
      .filter((d) => d.values.length);
  }, [usable, search]);

  return (
    <Menu
      label="Filters"
      icon={Filter}
      summary={count ? `${count} applied` : "All employees"}
      count={count || undefined}
      align="right"
      width="w-80"
    >
      <div className="sticky top-0 z-10 bg-white p-1 dark:bg-ink-900">
        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-2.5 text-ink-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Find a department, location, grade…"
            aria-label="Search filter values"
            className="h-8 w-full rounded-lg border border-ink-200 bg-white pl-7 pr-2 text-xs text-ink-900 placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-brand-500 dark:border-white/10 dark:bg-white/[0.04] dark:text-white"
          />
        </div>
      </div>

      {matching.length === 0 && (
        <p className="px-2.5 py-3 text-xs text-ink-500 dark:text-ink-400">
          {usable.length
            ? "Nothing matches that."
            : "Only one value on every dimension — upload an employee master to filter by department, location or grade."}
        </p>
      )}

      {matching.map((dimension) => (
        <div key={dimension.key} className="pb-1">
          <p className="px-2.5 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
            {dimension.label}
          </p>
          {dimension.values.map((value) => {
            const on = (filters[dimension.key] ?? []).includes(value);
            return (
              <button
                key={value}
                type="button"
                role="option"
                aria-selected={on}
                onClick={() => onToggle(dimension.key, value)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors",
                  on
                    ? "bg-brand-50 font-medium text-brand-900 dark:bg-brand-500/15 dark:text-brand-100"
                    : "text-ink-700 hover:bg-ink-50 dark:text-ink-200 dark:hover:bg-white/[0.06]",
                )}
              >
                <span
                  aria-hidden
                  className={cn(
                    "flex h-4 w-4 flex-shrink-0 items-center justify-center rounded border",
                    on
                      ? "border-brand-600 bg-brand-600 text-white"
                      : "border-ink-300 dark:border-white/20",
                  )}
                >
                  {on && <Check size={11} strokeWidth={3} />}
                </span>
                <span className="truncate">{value}</span>
              </button>
            );
          })}
        </div>
      ))}

      {count > 0 && (
        <button
          type="button"
          onClick={onClear}
          className="mt-1 flex w-full items-center justify-center gap-1.5 rounded-lg border-t border-ink-100 px-2.5 py-2 text-xs font-medium text-ink-600 hover:bg-ink-50 dark:border-white/5 dark:text-ink-300 dark:hover:bg-white/[0.06]"
        >
          <X size={12} /> Clear {count === 1 ? "filter" : "all filters"}
        </button>
      )}
    </Menu>
  );
}

/** The applied filters, shown outside the menu because they change the figures. */
export function ActiveFilters({
  dimensions,
  filters,
  onToggle,
  onClear,
}: {
  dimensions: DimensionMeta[];
  filters: Record<string, string[]>;
  onToggle: (key: string, value: string) => void;
  onClear: () => void;
}) {
  const labels = Object.fromEntries(dimensions.map((d) => [d.key, d.label]));
  const entries = Object.entries(filters).flatMap(([key, values]) =>
    values.map((value) => ({ key, value })),
  );
  if (!entries.length) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-ink-400">
        Showing only
      </span>
      {entries.map(({ key, value }) => (
        <button
          key={`${key}:${value}`}
          type="button"
          onClick={() => onToggle(key, value)}
          className="inline-flex items-center gap-1.5 rounded-full border border-brand-200 bg-brand-50 py-1 pl-2.5 pr-1.5 text-xs font-medium text-brand-800 hover:border-brand-400 dark:border-brand-500/40 dark:bg-brand-500/15 dark:text-brand-100"
        >
          <span className="text-brand-500 dark:text-brand-300">{labels[key] ?? key}:</span>
          {value}
          <X size={12} className="opacity-60" aria-label={`Remove ${value}`} />
        </button>
      ))}
      <button
        type="button"
        onClick={onClear}
        className="rounded-full px-2 py-1 text-xs font-medium text-ink-500 hover:bg-ink-100 dark:text-ink-400 dark:hover:bg-white/[0.06]"
      >
        Clear
      </button>
    </div>
  );
}
