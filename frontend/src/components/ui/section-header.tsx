import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function SectionHeader({
  eyebrow,
  title,
  description,
  actions,
  className,
}: {
  eyebrow?: string;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-4", className)}>
      <div className="min-w-0 max-w-2xl">
        {eyebrow && (
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-brand-600">
            {eyebrow}
          </p>
        )}
        <h2 className="font-display text-lg font-bold tracking-tight text-ink-900 sm:text-xl">
          {title}
        </h2>
        {description && (
          <p className="mt-1 text-sm leading-relaxed text-ink-500">{description}</p>
        )}
      </div>
      {actions && <div className="flex flex-shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}
