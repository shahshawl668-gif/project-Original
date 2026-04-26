"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  UploadCloud,
  ClipboardCheck,
  History,
  FolderArchive,
  Settings2,
  Layers,
  Code2,
  BarChart3,
  Building2,
  Menu,
  X,
  ChevronRight,
  FileSpreadsheet,
} from "lucide-react";
import { useState } from "react";

const navGroups = [
  {
    label: "Overview",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
    ],
  },
  {
    label: "Payroll",
    items: [
      { href: "/payroll/upload", label: "Upload & Validate", icon: UploadCloud },
      { href: "/payroll/results", label: "Results", icon: ClipboardCheck },
      { href: "/payroll/history", label: "Register History", icon: History },
    ],
  },
  {
    label: "CTC",
    items: [
      { href: "/ctc/upload", label: "Upload CTC", icon: FileSpreadsheet },
      { href: "/ctc/history", label: "CTC History", icon: FolderArchive },
    ],
  },
  {
    label: "Configuration",
    items: [
      { href: "/config/statutory", label: "Statutory Engine", icon: Settings2 },
      { href: "/config/components", label: "Salary Components", icon: Layers },
    ],
  },
  {
    label: "Rule Engine",
    items: [
      { href: "/rule-engine/formula", label: "Formulas", icon: Code2 },
      { href: "/rule-engine/slabs", label: "PT / LWF Slabs", icon: BarChart3 },
    ],
  },
];

function SidebarContent({ onClose }: {
  onClose?: () => void;
}) {
  const pathname = usePathname();

  return (
    <div className="flex flex-col h-full bg-slate-900 text-white">
      {/* Brand header */}
      <div className="flex items-center justify-between px-4 py-4 border-b border-slate-700/60">
        <Link href="/dashboard" className="flex items-center gap-2.5 min-w-0" onClick={onClose}>
          <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center flex-shrink-0">
            <Building2 size={16} className="text-white" />
          </div>
          <div className="min-w-0">
            <p className="font-semibold text-sm text-white leading-none">PayrollCheck</p>
            <p className="text-[11px] text-slate-400 truncate mt-0.5">India Payroll Audit</p>
          </div>
        </Link>
        {onClose && (
          <button onClick={onClose} className="text-slate-400 hover:text-white lg:hidden">
            <X size={18} />
          </button>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-4 px-2 space-y-5">
        {navGroups.map((group) => (
          <div key={group.label}>
            <p className="px-3 mb-1.5 text-[10px] uppercase tracking-widest text-slate-500 font-semibold select-none">
              {group.label}
            </p>
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const Icon = item.icon;
                const active = pathname === item.href || (item.href !== "/dashboard" && pathname.startsWith(item.href));
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={onClose}
                    className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-all ${
                      active
                        ? "bg-brand-600 text-white shadow-sm"
                        : "text-slate-400 hover:text-white hover:bg-slate-800"
                    }`}
                  >
                    <Icon size={15} className="flex-shrink-0" />
                    <span className="truncate">{item.label}</span>
                    {active && <ChevronRight size={13} className="ml-auto opacity-70 flex-shrink-0" />}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Brand footer */}
      <div className="border-t border-slate-700/60 px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-full bg-brand-700 flex items-center justify-center text-[10px] font-bold text-white flex-shrink-0">
            P
          </div>
          <p className="text-[11px] text-slate-400">PayrollCheck — India Payroll Audit</p>
        </div>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  // Derive page title from pathname
  const allItems = navGroups.flatMap((g) => g.items);
  const currentItem = allItems.find(
    (i) => pathname === i.href || (i.href !== "/dashboard" && pathname.startsWith(i.href)),
  );
  const pageTitle = currentItem?.label ?? "PayrollCheck";

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      {/* Desktop sidebar */}
      <div className="hidden lg:flex flex-col w-60 flex-shrink-0 shadow-xl">
        <SidebarContent />
      </div>

      {/* Mobile sidebar overlay */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden flex">
          <div
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
          />
          <div className="relative w-60 flex-shrink-0 shadow-2xl">
            <SidebarContent onClose={() => setMobileOpen(false)} />
          </div>
        </div>
      )}

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top bar */}
        <header className="flex items-center gap-3 px-4 lg:px-6 py-3.5 bg-white border-b border-slate-200 shadow-sm flex-shrink-0">
          <button
            onClick={() => setMobileOpen(true)}
            className="lg:hidden text-slate-500 hover:text-slate-900 transition-colors"
          >
            <Menu size={20} />
          </button>
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <span className="text-slate-400 text-xs">PayrollCheck</span>
            <ChevronRight size={13} className="text-slate-300" />
            <span className="font-medium text-slate-800">{pageTitle}</span>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden sm:block text-xs text-slate-400 bg-slate-100 px-2 py-1 rounded-md">
              PayrollCheck
            </span>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-4 lg:p-8">
          {children}
        </main>
      </div>
    </div>
  );
}
