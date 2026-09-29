"use client";

import Link from "next/link";
import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export type TabItem = { id: string; label: ReactNode; count?: number | null; href?: string };

/**
 * Underlined tabs. With `href` they are links (sub-pages); without, they are
 * an ARIA tablist with arrow-key movement between tabs.
 */
export function Tabs({
  items,
  value,
  onChange,
  className,
  label,
}: {
  items: TabItem[];
  value: string;
  onChange?: (id: string) => void;
  className?: string;
  label: string;
}) {
  const refs = useRef<(HTMLElement | null)[]>([]);
  const linkMode = items.every((i) => i.href);
  const onKey = (e: KeyboardEvent, idx: number) => {
    if (linkMode) return;
    const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!d) return;
    e.preventDefault();
    const next = (idx + d + items.length) % items.length;
    refs.current[next]?.focus();
    onChange?.(items[next].id);
  };
  return (
    <div
      role={linkMode ? undefined : "tablist"}
      aria-label={label}
      className={cn("scrollbar-thin -mb-px flex gap-5 overflow-x-auto border-b border-ink-200", className)}
    >
      {items.map((item, idx) => {
        const active = item.id === value;
        const cls = cn(
          "relative -mb-px inline-flex flex-shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-0.5 pb-2.5 pt-1 text-[13px] font-medium transition-colors",
          active ? "border-brand-600 text-ink-900" : "border-transparent text-ink-500 hover:border-ink-300 hover:text-ink-800",
        );
        const inner = (
          <>
            {item.label}
            {item.count !== undefined && item.count !== null ? (
              <span className={cn("num rounded-full px-1.5 text-[11px]", active ? "bg-brand-50 text-brand-800" : "bg-ink-100 text-ink-600")}>
                {item.count.toLocaleString("en-IN")}
              </span>
            ) : null}
          </>
        );
        return item.href ? (
          <Link key={item.id} href={item.href} aria-current={active ? "page" : undefined} className={cls}>
            {inner}
          </Link>
        ) : (
          <button
            key={item.id}
            ref={(el) => {
              refs.current[idx] = el;
            }}
            type="button"
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onKeyDown={(e) => onKey(e, idx)}
            onClick={() => onChange?.(item.id)}
            className={cls}
          >
            {inner}
          </button>
        );
      })}
    </div>
  );
}
