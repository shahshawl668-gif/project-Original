import type { ReactNode } from "react";
import { AlertCircle, AlertTriangle, CheckCircle2, Info } from "lucide-react";
import { cn } from "@/lib/utils";

type AlertVariant = "success" | "error" | "warning" | "info";

const styles: Record<AlertVariant, { wrap: string; iconWrap: string; icon: string }> = {
  success: {
    wrap: "border-success-200/80 bg-gradient-to-br from-success-50 to-white text-success-900 dark:border-success-500/25 dark:from-success-500/10 dark:to-ink-900/40 dark:text-success-100",
    iconWrap: "bg-success-500/10 ring-1 ring-success-500/30",
    icon: "text-success-600 dark:text-success-400",
  },
  error: {
    wrap: "border-danger-200/80 bg-gradient-to-br from-danger-50 to-white text-danger-900 dark:border-danger-500/25 dark:from-danger-500/10 dark:to-ink-900/40 dark:text-danger-100",
    iconWrap: "bg-danger-500/10 ring-1 ring-danger-500/30",
    icon: "text-danger-600 dark:text-danger-400",
  },
  warning: {
    wrap: "border-warning-200/80 bg-gradient-to-br from-warning-50 to-white text-warning-950 dark:border-warning-500/30 dark:from-warning-500/10 dark:to-ink-900/40 dark:text-warning-100",
    iconWrap: "bg-warning-500/10 ring-1 ring-warning-500/40",
    icon: "text-warning-600 dark:text-warning-400",
  },
  info: {
    wrap: "border-brand-200/70 bg-gradient-to-br from-brand-50 to-white text-ink-800 dark:border-brand-500/25 dark:from-brand-500/10 dark:to-ink-900/40 dark:text-ink-100",
    iconWrap: "bg-brand-500/10 ring-1 ring-brand-500/30",
    icon: "text-brand-600 dark:text-brand-300",
  },
};

const icons: Record<AlertVariant, typeof CheckCircle2> = {
  success: CheckCircle2,
  error: AlertCircle,
  warning: AlertTriangle,
  info: Info,
};

type AlertBannerProps = {
  variant: AlertVariant;
  title?: string;
  children: ReactNode;
  className?: string;
};

export function AlertBanner({ variant, title, children, className }: AlertBannerProps) {
  const s = styles[variant];
  const Icon = icons[variant];
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-3 rounded-2xl border p-4 text-sm leading-relaxed shadow-soft",
        s.wrap,
        className,
      )}
    >
      <span
        className={cn(
          "flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl",
          s.iconWrap,
        )}
      >
        <Icon className={cn("h-4 w-4", s.icon)} aria-hidden />
      </span>
      <div className="min-w-0 flex-1 pt-0.5">
        {title ? <p className="font-display text-[14px] font-semibold">{title}</p> : null}
        <div className={cn("text-[13px]", title && "mt-1")}>{children}</div>
      </div>
    </div>
  );
}
