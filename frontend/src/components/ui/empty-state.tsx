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
  /** `compact` for inside a card or table; the default fills a section. */
  size?: "default" | "compact";
};

/**
 * Nothing to show — and why, and what to do about it. The description should
 * say which of "nothing exists yet", "nothing matches your filters" and
 * "nothing was checked" this is: they are different claims.
 */
export function EmptyState({ icon, title, description, action, className, size = "default" }: EmptyStateProps) {
  const renderedIcon = (() => {
    if (!icon) return null;
    if (isValidElement(icon)) return icon;
    if (typeof icon === "function" || (typeof icon === "object" && icon !== null && "$$typeof" in (icon as object))) {
      return createElement(icon as LucideIcon, { size: 18, strokeWidth: 1.75, className: "text-ink-500", "aria-hidden": true });
    }
    return icon as ReactNode;
  })();

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-dashed border-ink-200 bg-white text-center",
        size === "compact" ? "px-4 py-8" : "px-6 py-12",
        className,
      )}
    >
      {renderedIcon ? (
        <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-lg border border-ink-200 bg-ink-50">
          {renderedIcon}
        </div>
      ) : null}
      <p className="text-sm font-semibold text-ink-900">{title}</p>
      {description ? (
        <div className="mt-1 max-w-md text-[13px] leading-relaxed text-ink-500">{description}</div>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}
