"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Keeps keyboard focus inside an open overlay, closes it on Escape, and hands
 * focus back to whatever opened it. Without the last part a keyboard user who
 * closes a drawer lands at the top of the page and loses their row.
 */
function useModalFocus(open: boolean, panel: React.RefObject<HTMLElement | null>, onClose: () => void) {
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const node = panel.current;
    const first = node?.querySelector<HTMLElement>("[data-autofocus]") ?? node;
    first?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        closeRef.current();
        return;
      }
      if (e.key !== "Tab" || !node) return;
      const items = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.offsetParent !== null);
      if (!items.length) return;
      const [a, z] = [items[0], items[items.length - 1]];
      if (e.shiftKey && (document.activeElement === a || document.activeElement === node)) {
        e.preventDefault();
        z.focus();
      } else if (!e.shiftKey && document.activeElement === z) {
        e.preventDefault();
        a.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      if (opener && document.contains(opener)) opener.focus({ preventScroll: true });
    };
  }, [open, panel]);
}

type OverlayProps = {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
};

/**
 * A side panel for a quick look — an employee, a finding — without leaving
 * the table. Anything that needs more room than this gets its own page, and
 * the drawer links to it.
 */
export function Drawer({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  className,
  width = "md",
}: OverlayProps & { width?: "md" | "lg" | "xl" }) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useModalFocus(open, panel, onClose);
  if (!open || typeof document === "undefined") return null;
  return createPortal(
    <div className="fixed inset-0 z-[60] flex justify-end">
      <div className="absolute inset-0 animate-fade-in bg-ink-950/30" aria-hidden onClick={onClose} />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={cn(
          "relative flex h-full w-full animate-slide-in-right flex-col border-l border-ink-200 bg-white shadow-elevated outline-none",
          width === "md" && "sm:max-w-md",
          width === "lg" && "sm:max-w-2xl",
          width === "xl" && "sm:max-w-4xl",
          className,
        )}
      >
        <div className="flex items-start gap-3 border-b border-ink-200 px-5 py-3.5">
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="truncate text-[15px] font-semibold text-ink-900">{title}</h2>
            {description ? <div className="mt-0.5 text-xs text-ink-500">{description}</div> : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="-mr-1.5 rounded-md p-1.5 text-ink-500 transition-colors hover:bg-ink-100 hover:text-ink-900"
          >
            <X size={16} />
          </button>
        </div>
        <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer ? <div className="flex items-center justify-end gap-2 border-t border-ink-200 px-5 py-3">{footer}</div> : null}
      </div>
    </div>,
    document.body,
  );
}

/** A centred dialog for a decision: confirm, name something, choose. */
export function Dialog({ open, onClose, title, description, children, footer, className }: OverlayProps) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useModalFocus(open, panel, onClose);
  if (!open || typeof document === "undefined") return null;
  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-end justify-center p-0 sm:items-center sm:p-6">
      <div className="absolute inset-0 animate-fade-in bg-ink-950/30" aria-hidden onClick={onClose} />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={cn(
          "relative w-full animate-fade-up rounded-t-xl border border-ink-200 bg-white shadow-elevated outline-none sm:max-w-lg sm:rounded-xl",
          className,
        )}
      >
        <div className="px-5 pb-2 pt-4">
          <h2 id={titleId} className="text-[15px] font-semibold text-ink-900">{title}</h2>
          {description ? <div className="mt-1 text-[13px] leading-relaxed text-ink-500">{description}</div> : null}
        </div>
        <div className="px-5 py-2">{children}</div>
        {footer ? <div className="flex items-center justify-end gap-2 px-5 pb-4 pt-2">{footer}</div> : null}
      </div>
    </div>,
    document.body,
  );
}
