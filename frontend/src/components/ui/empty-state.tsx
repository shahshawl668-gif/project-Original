import type { ReactNode } from "react";
import { isValidElement, createElement } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

type EmptyStateProps = {
  icon?: LucideIcon | ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
};

export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  const renderedIcon = (() => {
    if (!icon) return null;
    if (isValidElement(icon)) return icon;
    if (typeof icon === "function" || (typeof icon === "object" && icon !== null && "$$typeof" in (icon as object))) {
      return createElement(icon as LucideIcon, {
        size: 22,
        strokeWidth: 1.75,
        className: "text-brand-600 dark:text-brand-300",
      });
    }
    return icon as ReactNode;
  })();

  return (
    <div
      className={cn(
        "relative flex flex-col items-center justify-center overflow-hidden rounded-2xl border border-dashed border-ink-200 bg-gradient-to-br from-white via-ink-50/40 to-white px-6 py-14 text-center",
        "dark:border-white/10 dark:from-ink-900/40 dark:via-ink-900/20 dark:to-ink-950/40",
        className,
      )}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute -top-20 left-1/2 h-40 w-40 -translate-x-1/2 rounded-full bg-gradient-to-br from-brand-200/40 to-accent-200/30 blur-3xl dark:from-brand-500/30 dark:to-accent-500/20"
      />
      {renderedIcon ? (
        <div className="relative mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-white shadow-soft ring-1 ring-ink-900/[0.05] dark:bg-ink-900 dark:ring-white/10">
          {renderedIcon}
        </div>
      ) : null}
      <p className="relative font-display text-base font-semibold tracking-tight text-ink-900 dark:text-white">
        {title}
      </p>
      {description ? (
        <p className="relative mt-1.5 max-w-sm text-sm leading-relaxed text-ink-500 dark:text-ink-300">
          {description}
        </p>
      ) : null}
      {action ? <div className="relative mt-5">{action}</div> : null}
    </div>
  );
}
