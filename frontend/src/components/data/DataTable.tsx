"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Columns3, Rows3 } from "lucide-react";

import { cn } from "@/lib/utils";

export type Column<T> = {
  id: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /** Right-aligned, tabular figures. */
  numeric?: boolean;
  /** Pinned to the left while the table scrolls sideways. Use for the row's identity. */
  pin?: boolean;
  /** Server sort key; the header becomes a sort control. */
  sortKey?: string;
  /** Can be hidden from the column menu (identity columns cannot). */
  hideable?: boolean;
  /** Hidden until someone turns it on. */
  defaultHidden?: boolean;
  className?: string;
  headerClassName?: string;
};

export type Sort = { key: string; order: "asc" | "desc" };
type Density = "comfortable" | "compact";

function readPrefs(id: string): { density?: Density; hidden?: string[] } {
  try {
    return JSON.parse(localStorage.getItem(`pol_table:${id}`) || "{}");
  } catch {
    return {};
  }
}
function writePrefs(id: string, prefs: { density: Density; hidden: string[] }) {
  try {
    localStorage.setItem(`pol_table:${id}`, JSON.stringify(prefs));
  } catch {
    /* preferences are a convenience */
  }
}

/**
 * A table for records the server pages: sticky header, identity column pinned
 * for sideways scrolling, numbers right-aligned, density and visible columns
 * remembered per table on this device.
 *
 * Refreshing keeps the previous rows on screen under a thin progress line —
 * a table that blanks on every filter change loses the reader's place. Rows
 * are focusable: ↑/↓ move between them, Enter opens the row.
 */
export function DataTable<T>({
  id,
  columns,
  rows,
  rowKey,
  loading,
  refreshing,
  error,
  empty,
  onRowOpen,
  rowLabel,
  sort,
  onSort,
  selectable,
  selected,
  onSelectedChange,
  toolbar,
  footer,
  caption,
  minWidth = "48rem",
  maxHeight,
}: {
  id: string;
  columns: Column<T>[];
  rows: T[] | undefined;
  rowKey: (row: T) => string;
  loading?: boolean;
  refreshing?: boolean;
  error?: ReactNode;
  empty?: ReactNode;
  onRowOpen?: (row: T) => void;
  /** What a screen reader says for a row's open action. */
  rowLabel?: (row: T) => string;
  sort?: Sort;
  onSort?: (sort: Sort) => void;
  selectable?: boolean;
  selected?: Set<string>;
  onSelectedChange?: (next: Set<string>) => void;
  toolbar?: ReactNode;
  footer?: ReactNode;
  caption: string;
  minWidth?: string;
  maxHeight?: string;
}) {
  const [density, setDensity] = useState<Density>("comfortable");
  const [hidden, setHidden] = useState<string[]>(() => columns.filter((c) => c.defaultHidden).map((c) => c.id));
  const [menu, setMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLTableSectionElement>(null);

  useEffect(() => {
    const p = readPrefs(id);
    if (p.density) setDensity(p.density);
    if (p.hidden) setHidden(p.hidden);
  }, [id]);
  useEffect(() => {
    if (!menu) return;
    const close = (e: MouseEvent) => menuRef.current && !menuRef.current.contains(e.target as Node) && setMenu(false);
    const esc = (e: globalThis.KeyboardEvent) => e.key === "Escape" && setMenu(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [menu]);

  const visible = useMemo(() => columns.filter((c) => !hidden.includes(c.id)), [columns, hidden]);
  const setPrefs = (d: Density, h: string[]) => {
    setDensity(d);
    setHidden(h);
    writePrefs(id, { density: d, hidden: h });
  };

  const cellPad = density === "compact" ? "py-1" : "py-2";
  const keys = (rows ?? []).map(rowKey);
  const allSelected = !!selectable && keys.length > 0 && keys.every((k) => selected?.has(k));
  const someSelected = !!selectable && keys.some((k) => selected?.has(k));

  const onRowKey = (e: KeyboardEvent<HTMLTableRowElement>, row: T) => {
    if (e.key === "Enter" && onRowOpen) {
      e.preventDefault();
      onRowOpen(row);
      return;
    }
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const trs = Array.from(bodyRef.current?.querySelectorAll<HTMLTableRowElement>("tr[data-row]") ?? []);
    const at = trs.indexOf(e.currentTarget);
    trs[Math.min(trs.length - 1, Math.max(0, at + (e.key === "ArrowDown" ? 1 : -1)))]?.focus();
  };

  const colCount = visible.length + (selectable ? 1 : 0);

  return (
    <div className="overflow-hidden rounded-xl border border-ink-200 bg-white shadow-soft">
      <div className="flex flex-wrap items-center gap-2 border-b border-ink-100 px-3 py-2">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">{toolbar}</div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setPrefs(density === "compact" ? "comfortable" : "compact", hidden)}
            aria-pressed={density === "compact"}
            title={density === "compact" ? "Comfortable rows" : "Compact rows"}
            className="inline-flex h-8 items-center gap-1 rounded-lg px-2 text-xs text-ink-600 hover:bg-ink-100"
          >
            <Rows3 size={14} aria-hidden />
            <span className="hidden sm:inline">{density === "compact" ? "Compact" : "Comfortable"}</span>
          </button>
          {columns.some((c) => c.hideable) ? (
            <div className="relative" ref={menuRef}>
              <button
                type="button"
                onClick={() => setMenu((v) => !v)}
                aria-expanded={menu}
                aria-haspopup="true"
                className="inline-flex h-8 items-center gap-1 rounded-lg px-2 text-xs text-ink-600 hover:bg-ink-100"
              >
                <Columns3 size={14} aria-hidden />
                <span className="hidden sm:inline">Columns</span>
              </button>
              {menu ? (
                <div className="absolute right-0 z-30 mt-1 w-56 animate-fade-up rounded-xl border border-ink-200 bg-white p-1 shadow-elevated">
                  {columns.filter((c) => c.hideable).map((c) => (
                    <label key={c.id} className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px] text-ink-700 hover:bg-ink-50">
                      <input
                        type="checkbox"
                        className="accent-brand-600"
                        checked={!hidden.includes(c.id)}
                        onChange={(e) => setPrefs(density, e.target.checked ? hidden.filter((h) => h !== c.id) : [...hidden, c.id])}
                      />
                      {c.header}
                    </label>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>

      <div className="relative">
        {refreshing ? (
          <div className="absolute inset-x-0 top-0 z-30 h-0.5 overflow-hidden bg-brand-100" role="progressbar" aria-label="Refreshing">
            <div className="h-full w-1/3 animate-indeterminate bg-brand-500" />
          </div>
        ) : null}
        <div className="scrollbar-thin overflow-auto" style={maxHeight ? { maxHeight } : undefined}>
          <table className="w-full border-separate border-spacing-0 text-[13px]" style={{ minWidth }} aria-busy={loading || refreshing}>
            <caption className="sr-only">{caption}</caption>
            <thead>
              <tr>
                {selectable ? (
                  <th scope="col" className="sticky left-0 top-0 z-20 w-9 border-b border-ink-200 bg-ink-50 px-3">
                    <input
                      type="checkbox"
                      aria-label="Select all rows on this page"
                      className="accent-brand-600"
                      checked={allSelected}
                      ref={(el) => {
                        if (el) el.indeterminate = !allSelected && someSelected;
                      }}
                      onChange={() => {
                        const next = new Set(selected);
                        if (allSelected) keys.forEach((k) => next.delete(k));
                        else keys.forEach((k) => next.add(k));
                        onSelectedChange?.(next);
                      }}
                    />
                  </th>
                ) : null}
                {visible.map((c) => {
                  const active = sort && c.sortKey === sort.key;
                  return (
                    <th
                      key={c.id}
                      scope="col"
                      aria-sort={active ? (sort!.order === "asc" ? "ascending" : "descending") : undefined}
                      className={cn(
                        "sticky top-0 z-10 h-9 whitespace-nowrap border-b border-ink-200 bg-ink-50 px-3 text-left text-xs font-medium text-ink-500",
                        c.numeric && "text-right",
                        c.pin && (selectable ? "left-9 z-20" : "left-0 z-20"),
                        c.headerClassName,
                      )}
                    >
                      {c.sortKey && onSort ? (
                        <button
                          type="button"
                          onClick={() => onSort({ key: c.sortKey!, order: active && sort!.order === "desc" ? "asc" : "desc" })}
                          className={cn("inline-flex items-center gap-1 hover:text-ink-900", active && "text-ink-900")}
                        >
                          {c.header}
                          {active ? (sort!.order === "asc" ? <ArrowUp size={12} aria-hidden /> : <ArrowDown size={12} aria-hidden />) : null}
                        </button>
                      ) : (
                        c.header
                      )}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody ref={bodyRef}>
              {error ? (
                <tr><td colSpan={colCount} className="px-4 py-8">{error}</td></tr>
              ) : loading && !rows ? (
                Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i}>
                    <td colSpan={colCount} className="border-b border-ink-100 px-3 py-2.5">
                      <div className="h-3 w-full animate-pulse-soft rounded bg-ink-100" />
                    </td>
                  </tr>
                ))
              ) : !rows || rows.length === 0 ? (
                <tr><td colSpan={colCount} className="px-4 py-10 text-center text-[13px] text-ink-500">{empty ?? "Nothing to show."}</td></tr>
              ) : (
                rows.map((row) => {
                  const k = rowKey(row);
                  const isSel = selected?.has(k);
                  return (
                    <tr
                      key={k}
                      data-row
                      tabIndex={onRowOpen ? 0 : -1}
                      aria-label={onRowOpen && rowLabel ? rowLabel(row) : undefined}
                      onKeyDown={(e) => onRowKey(e, row)}
                      onClick={(e) => {
                        if (!onRowOpen) return;
                        const t = e.target as HTMLElement;
                        if (t.closest("a,button,input,select,label")) return;
                        onRowOpen(row);
                      }}
                      className={cn(
                        "group/row outline-none transition-colors duration-fast focus-visible:bg-brand-50",
                        onRowOpen && "cursor-pointer",
                        isSel ? "bg-brand-50/70" : "hover:bg-ink-50",
                      )}
                    >
                      {selectable ? (
                        <td className={cn("sticky left-0 z-[1] w-9 border-b border-ink-100 px-3", isSel ? "bg-brand-50" : "bg-white group-hover/row:bg-ink-50")}>
                          <input
                            type="checkbox"
                            className="accent-brand-600"
                            aria-label={rowLabel ? `Select ${rowLabel(row)}` : "Select row"}
                            checked={!!isSel}
                            onChange={() => {
                              const next = new Set(selected);
                              if (isSel) next.delete(k);
                              else next.add(k);
                              onSelectedChange?.(next);
                            }}
                          />
                        </td>
                      ) : null}
                      {visible.map((c) => (
                        <td
                          key={c.id}
                          className={cn(
                            "border-b border-ink-100 px-3 align-middle text-ink-700",
                            cellPad,
                            c.numeric && "num whitespace-nowrap text-right",
                            c.pin && cn("sticky z-[1]", selectable ? "left-9" : "left-0", isSel ? "bg-brand-50" : "bg-white group-hover/row:bg-ink-50 group-focus-visible/row:bg-brand-50"),
                            c.className,
                          )}
                        >
                          {c.cell(row)}
                        </td>
                      ))}
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
      {footer ? <div className="border-t border-ink-100 px-3 py-2">{footer}</div> : null}
    </div>
  );
}

/** "1–50 of 8,000" with previous/next. The total is always stated. */
export function Pagination({
  page,
  pages,
  total,
  pageSize,
  onPage,
  noun = "rows",
}: {
  page: number;
  pages: number;
  total: number;
  pageSize: number;
  onPage: (p: number) => void;
  noun?: string;
}) {
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-ink-500">
      <span className="num" aria-live="polite">
        {total === 0 ? `No ${noun}` : `${from.toLocaleString("en-IN")}–${to.toLocaleString("en-IN")} of ${total.toLocaleString("en-IN")} ${noun}`}
      </span>
      {pages > 1 ? (
        <div className="flex items-center gap-1">
          <button
            type="button"
            className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-ink-200 bg-white text-ink-700 hover:bg-ink-50 disabled:opacity-40"
            disabled={page <= 1}
            onClick={() => onPage(page - 1)}
            aria-label="Previous page"
          >
            <ChevronLeft size={14} />
          </button>
          <span className="num px-1.5">Page {page} of {pages.toLocaleString("en-IN")}</span>
          <button
            type="button"
            className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-ink-200 bg-white text-ink-700 hover:bg-ink-50 disabled:opacity-40"
            disabled={page >= pages}
            onClick={() => onPage(page + 1)}
            aria-label="Next page"
          >
            <ChevronRight size={14} />
          </button>
        </div>
      ) : null}
    </div>
  );
}

/** A compact filter control: a native select, labelled, for server-side filters. */
export function FilterSelect({
  label,
  value,
  onChange,
  options,
  allLabel,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  allLabel: string;
}) {
  // Named with aria-label rather than a wrapping <label>: a label around a
  // select folds every option's text into the control's accessible name.
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={cn(
        "h-8 max-w-[14rem] rounded-lg border bg-white px-2 text-[13px]",
        value ? "border-brand-300 bg-brand-50/50 text-brand-900" : "border-ink-200 text-ink-700",
      )}
    >
      <option value="">{allLabel}</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}
