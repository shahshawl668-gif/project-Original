import type { ReactNode } from "react";
import { AlertCircle, AlertTriangle, CheckCircle2, Info } from "lucide-react";
import { cn } from "@/lib/utils";

type AlertVariant = "success" | "error" | "warning" | "info";

const styles: Record<AlertVariant, string> = {
  success:
    "border-emerald-200/80 bg-emerald-50/90 text-emerald-900 [&>svg]:text-emerald-600",
  error: "border-red-200/80 bg-red-50/90 text-red-900 [&>svg]:text-red-600",
  warning:
    "border-amber-200/80 bg-amber-50/90 text-amber-950 [&>svg]:text-amber-600",
  info: "border-slate-200/80 bg-slate-50 text-slate-800 [&>svg]:text-slate-500",
};

const icons: Record<AlertVariant, ReactNode> = {
  success: <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden />,
  error: <AlertCircle className="h-4 w-4 shrink-0" aria-hidden />,
  warning: <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />,
  info: <Info className="h-4 w-4 shrink-0" aria-hidden />,
};

type AlertBannerProps = {
  variant: AlertVariant;
  title?: string;
  children: ReactNode;
  className?: string;
};

export function AlertBanner({ variant, title, children, className }: AlertBannerProps) {
  return (
    <div
      role="alert"
      className={cn(
        "flex gap-3 rounded-xl border px-4 py-3 text-sm leading-relaxed shadow-sm",
        styles[variant],
        className,
      )}
    >
      {icons[variant]}
      <div className="min-w-0 pt-px">
        {title ? <p className="font-medium">{title}</p> : null}
        <div className={cn(title && "mt-0.5")}>{children}</div>
      </div>
    </div>
  );
}
