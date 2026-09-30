import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type PageHeaderProps = {
  /** Accepted for older callers and not shown: the breadcrumb in the header
   *  already names the section, and saying it twice pushed the work down. */
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
export function PageHeader({ title, description, actions, meta, className }: PageHeaderProps) {
  return (
    <header className={cn("flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-6", className)}>
      <div className="min-w-0 space-y-1">
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
