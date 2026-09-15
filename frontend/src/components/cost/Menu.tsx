"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * A control that keeps its contents out of the way until asked for.
 *
 * The cost dashboard has nine reportable dimensions and a taxonomy of fifteen
 * measures. Laid out flat that is five rows of controls before a reader reaches
 * a number — the data ends up below the fold on the machine it is presented
 * from. So every choice lives behind one of these, and the trigger states the
 * current selection so nothing has to be opened to be read.
 */
export function Menu({
  label,
  summary,
  count,
  icon: Icon,
  children,
  align = "left",
  width = "w-72",
}: {
  label: string;
  summary: string;
  count?: number;
  icon?: React.ComponentType<{ size?: number | string; className?: string }>;
  children: React.ReactNode | ((close: () => void) => React.ReactNode);
  align?: "left" | "right";
  width?: string;
}) {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div className="relative" ref={container}>
      <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wide text-ink-400">
        {label}
      </span>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="true"
        className={cn(
          "inline-flex h-9 w-full items-center justify-between gap-2 rounded-lg border px-3 text-sm font-medium transition-colors",
          open
            ? "border-brand-500 bg-brand-50 text-brand-900 dark:border-brand-500/60 dark:bg-brand-500/10 dark:text-brand-100"
            : "border-ink-200 bg-white text-ink-800 hover:bg-ink-50 dark:border-white/10 dark:bg-white/[0.04] dark:text-ink-100 dark:hover:bg-white/[0.07]",
        )}
      >
        <span className="flex min-w-0 items-center gap-2">
          {Icon && <Icon size={14} className="flex-shrink-0 opacity-70" />}
          <span className="truncate">{summary}</span>
        </span>
        <span className="flex flex-shrink-0 items-center gap-1.5">
          {count ? (
            <span className="rounded-full bg-brand-600 px-1.5 py-px text-[10px] font-bold text-white">
              {count}
            </span>
          ) : null}
          <ChevronDown size={14} className={cn("opacity-60 transition-transform", open && "rotate-180")} />
        </span>
      </button>

      {open && (
        <div
          className={cn(
            "absolute z-40 mt-1.5 max-h-[22rem] overflow-y-auto rounded-xl border border-ink-200/70 bg-white p-1.5 shadow-elevated",
            "dark:border-white/10 dark:bg-ink-900",
            align === "right" ? "right-0" : "left-0",
            width,
          )}
        >
          {typeof children === "function" ? children(() => setOpen(false)) : children}
        </div>
      )}
    </div>
  );
}

/** One selectable row inside a Menu. */
export function MenuItem({
  selected,
  onClick,
  children,
  hint,
}: {
  selected?: boolean;
  onClick: () => void;
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      onClick={onClick}
      className={cn(
        "flex w-full flex-col items-start gap-0.5 rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors",
        selected
          ? "bg-brand-50 font-medium text-brand-900 dark:bg-brand-500/15 dark:text-brand-100"
          : "text-ink-700 hover:bg-ink-50 dark:text-ink-200 dark:hover:bg-white/[0.06]",
      )}
    >
      <span>{children}</span>
      {hint && <span className="text-[11px] font-normal text-ink-500 dark:text-ink-400">{hint}</span>}
    </button>
  );
}
