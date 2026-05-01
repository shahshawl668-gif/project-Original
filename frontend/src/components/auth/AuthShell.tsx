import type { ReactNode } from "react";
import Link from "next/link";
import { Building2 } from "lucide-react";

/** Split auth layout — product story left (lg), form right — matches premium SaaS sign-in flows */
export function AuthShell({
  brandTitle,
  brandSubtitle,
  children,
}: {
  brandTitle?: string;
  brandSubtitle?: string;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-[#f6f8fc]">
      <div className="mx-auto flex min-h-screen max-w-[1200px] flex-col lg:flex-row">
        <aside className="relative hidden overflow-hidden lg:flex lg:w-[44%] lg:flex-col lg:justify-between lg:px-12 lg:py-14">
          <div
            className="absolute inset-0 bg-gradient-to-br from-brand-600 via-brand-700 to-[#312e81]"
            aria-hidden
          />
          <div className="absolute inset-0 bg-[radial-gradient(ellipse_80%_60%_at_20%_-10%,rgba(255,255,255,0.22),transparent)]" aria-hidden />
          <div className="relative z-10">
            <Link href="/dashboard" className="inline-flex items-center gap-2.5 rounded-xl py-2 text-white/95">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/15 ring-1 ring-white/25 backdrop-blur">
                <Building2 className="h-5 w-5" strokeWidth={1.75} />
              </span>
              <span className="text-sm font-semibold tracking-tight">PayrollCheck</span>
            </Link>
            <h2 className="mt-14 max-w-sm text-balance text-3xl font-semibold leading-[1.15] tracking-tight text-white">
              {brandTitle ?? "India payroll audits, without spreadsheet chaos"}
            </h2>
            <p className="mt-5 max-w-sm text-[15px] leading-relaxed text-indigo-100/95">
              {brandSubtitle ??
                "Validate statutory deductions, reconcile registers, and leave a clear audit trail for every payroll run."}
            </p>
          </div>
          <p className="relative z-10 mt-14 text-xs font-medium uppercase tracking-widest text-white/55">
            Statutory readiness · Tenant-isolated · Config-first
          </p>
        </aside>

        <main className="flex flex-1 flex-col justify-center px-5 py-12 sm:px-10 lg:px-16 lg:py-14">
          <div className="mx-auto w-full max-w-[420px]">{children}</div>
        </main>
      </div>
    </div>
  );
}
