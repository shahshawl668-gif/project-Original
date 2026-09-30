import type { ReactNode } from "react";
import { AlertCircle, AlertTriangle, CheckCircle2, Info } from "lucide-react";
import { cn } from "@/lib/utils";

type AlertVariant = "success" | "error" | "warning" | "info";

const styles: Record<AlertVariant, { wrap: string; icon: string }> = {
  success: { wrap: "border-success-200 bg-success-50 text-success-950", icon: "text-success-600" },
  error: { wrap: "border-danger-200 bg-danger-50 text-danger-950", icon: "text-danger-600" },
  warning: { wrap: "border-warning-200 bg-warning-50 text-warning-950", icon: "text-warning-600" },
  info: { wrap: "border-brand-200 bg-brand-50 text-ink-800", icon: "text-brand-600" },
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
  /** Technical detail, kept behind a disclosure so the plain message leads. */
  details?: ReactNode;
  action?: ReactNode;
};

/**
 * An inline message. Only errors interrupt a screen reader (`role="alert"`);
 * the rest are announced politely, so a page with three notices does not
 * shout three times on load.
 */
export function AlertBanner({ variant, title, children, className, details, action }: AlertBannerProps) {
  const s = styles[variant];
  const Icon = icons[variant];
  return (
    <div
      role={variant === "error" ? "alert" : "status"}
      className={cn("flex items-start gap-2.5 rounded-lg border px-3.5 py-3 text-[13px] leading-relaxed", s.wrap, className)}
    >
      <Icon className={cn("mt-0.5 h-4 w-4 flex-shrink-0", s.icon)} aria-hidden />
      <div className="min-w-0 flex-1">
        {title ? <p className="font-semibold">{title}</p> : null}
        <div className={cn(title && "mt-0.5")}>{children}</div>
        {details ? (
          <details className="mt-1.5 text-xs">
            <summary className="cursor-pointer select-none text-ink-600 hover:text-ink-900">Technical details</summary>
            <div className="mt-1.5 break-words font-mono text-[11px] text-ink-600">{details}</div>
          </details>
        ) : null}
      </div>
      {action ? <div className="flex-shrink-0">{action}</div> : null}
    </div>
  );
}
