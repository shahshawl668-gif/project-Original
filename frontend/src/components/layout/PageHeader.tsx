import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type PageHeaderProps = {
  /** The section this page belongs to. The shell's breadcrumb already says
   *  so; kept for pages that use it as a subtitle-like label. */
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  /** A row under the title for status, period or run context. */
  meta?: ReactNode;
  className?: string;
};

/**
 * Title, one line on what the page is for, and the page's actions on the
 * right. Compact on purpose: the first screen of a working page belongs to
 * the work.
 */
export function PageHeader({ eyebrow, title, description, actions, meta, className }: PageHeaderProps) {
  return (
    <header className={cn("flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-6", className)}>
      <div className="min-w-0 space-y-1">
        {eyebrow && <p className="text-xs font-medium text-brand-700">{eyebrow}</p>}
        <h1 className="text-[22px] font-semibold leading-tight tracking-tight text-ink-900">{title}</h1>
        {description ? (
          <div className="max-w-3xl text-[13.5px] leading-relaxed text-ink-500">{description}</div>
        ) : null}
        {meta ? <div className="flex flex-wrap items-center gap-2 pt-1 text-xs text-ink-500">{meta}</div> : null}
      </div>
      {actions ? <div className="flex flex-shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
