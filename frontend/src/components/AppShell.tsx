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
  Menu,
  X,
  ChevronRight,
  FileSpreadsheet,
  Ban,
  LogOut,
  Shield,
  Search,
  Bell,
  Sparkles,
  ChevronDown,
  Building2,
  Command,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/context/AuthContext";
import { ApiHealthBadge } from "@/components/ApiHealthBadge";

const navGroups = [
  {
    label: "Overview",
    items: [{ href: "/dashboard", label: "Dashboard", icon: LayoutDashboard }],
  },
  {
    label: "Payroll",
    items: [
      { href: "/payroll/upload", label: "Upload & validate", icon: UploadCloud },
      { href: "/payroll/results", label: "Results", icon: ClipboardCheck },
      { href: "/payroll/history", label: "Register history", icon: History },
    ],
  },
  {
    label: "CTC",
    items: [
      { href: "/ctc/upload", label: "Upload CTC", icon: FileSpreadsheet },
      { href: "/ctc/history", label: "CTC history", icon: FolderArchive },
    ],
  },
  {
    label: "Configuration",
    items: [
      { href: "/config/statutory", label: "Statutory engine", icon: Settings2 },
      { href: "/config/components", label: "Salary components", icon: Layers },
      { href: "/config/rules", label: "Rule suppressions", icon: Ban },
    ],
  },
  {
    label: "Rule engine",
    items: [
      { href: "/rule-engine/formula", label: "Formulas", icon: Code2 },
      { href: "/rule-engine/slabs", label: "PT / LWF slabs", icon: BarChart3 },
    ],
  },
];

function useNavGroups() {
  const { user } = useAuth();
  return useMemo(() => {
    return navGroups.map((g) => {
      if (g.label !== "Configuration") return g;
      const adminItems =
        user?.role === "admin"
          ? [{ href: "/admin/users", label: "Users & roles", icon: Shield }]
          : [];
      return { ...g, items: [...adminItems, ...g.items] };
    });
  }, [user?.role]);
}

function Sidebar({
  groups,
  onClose,
}: {
  groups: ReturnType<typeof useNavGroups>;
  onClose?: () => void;
}) {
  const pathname = usePathname();

  return (
    <div className="relative flex h-full flex-col overflow-hidden bg-ink-950 text-ink-100">
      {/* ambient glow */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.55]"
        style={{
          background:
            "radial-gradient(60% 40% at 50% 0%, rgba(124,58,237,0.35) 0%, transparent 60%), radial-gradient(50% 50% at 0% 100%, rgba(56,189,248,0.18) 0%, transparent 50%)",
        }}
      />
      <div className="relative flex items-center justify-between gap-3 px-5 pb-5 pt-6">
        <Link href="/dashboard" className="group flex min-w-0 items-center gap-3" onClick={onClose}>
          <div className="relative flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 via-accent-500 to-pink-500 shadow-[0_8px_28px_-6px_rgba(168,85,247,0.55)]">
            <Sparkles size={18} className="text-white" strokeWidth={2.25} aria-hidden />
          </div>
          <div className="min-w-0">
            <p className="text-[15px] font-bold leading-tight tracking-tight text-white">
              PayrollCheck
            </p>
            <p className="mt-0.5 truncate text-[10px] font-semibold uppercase tracking-[0.18em] text-ink-300">
              India · Audit grade
            </p>
          </div>
        </Link>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-ink-300 transition-colors hover:bg-white/10 hover:text-white lg:hidden"
            aria-label="Close menu"
          >
            <X size={18} />
          </button>
        )}
      </div>

      {/* workspace pill */}
      <div className="relative px-3">
        <button
          type="button"
          className="group flex w-full items-center gap-3 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 text-left transition-colors hover:bg-white/[0.06]"
        >
          <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-brand-500/40 to-accent-500/40 ring-1 ring-white/10">
            <Building2 size={14} className="text-white" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-xs font-semibold text-white">Workspace</span>
            <span className="block truncate text-[10px] text-ink-300">Tenant · Production</span>
          </span>
          <ChevronDown size={14} className="text-ink-400 transition-colors group-hover:text-white" />
        </button>
      </div>

      <nav className="scrollbar-thin relative mt-5 flex-1 space-y-5 overflow-y-auto px-3 pb-6">
        {groups.map((group) => (
          <div key={group.label}>
            <p className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.2em] text-ink-400">
              {group.label}
            </p>
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const Icon = item.icon;
                const active =
                  pathname === item.href ||
                  (item.href !== "/dashboard" && pathname.startsWith(item.href));
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={onClose}
                    className={`group relative flex items-center gap-3 rounded-lg px-3 py-2 text-[13px] font-medium transition-all ${
                      active
                        ? "bg-white/[0.08] text-white shadow-[inset_0_0_0_1px_rgba(255,255,255,0.08)]"
                        : "text-ink-200 hover:bg-white/[0.04] hover:text-white"
                    }`}
                  >
                    {active && (
                      <span
                        aria-hidden
                        className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-gradient-to-b from-brand-400 to-accent-500"
                      />
                    )}
                    <Icon
                      size={16}
                      strokeWidth={active ? 2.25 : 1.85}
                      className={`flex-shrink-0 transition-colors ${
                        active
                          ? "text-brand-300"
                          : "text-ink-400 group-hover:text-white"
                      }`}
                    />
                    <span className="truncate">{item.label}</span>
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className="relative border-t border-white/5 px-4 py-4">
        <div className="rounded-xl border border-white/10 bg-gradient-to-br from-white/[0.04] to-white/[0.01] p-3">
          <p className="text-[11px] font-semibold text-white">Production status</p>
          <p className="mt-1 text-[10px] leading-relaxed text-ink-300">
            Statutory rules current as of FY 2025-26 · PF · ESIC · PT · LWF · IT
          </p>
          <div className="mt-2.5">
            <ApiHealthBadge />
          </div>
        </div>
      </div>
    </div>
  );
}

function ProfileMenu() {
  const { user, isAuthenticated, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    if (open) document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  if (!isAuthenticated || !user) {
    return (
      <Link
        href="/login"
        className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-br from-brand-600 to-accent-600 px-3.5 py-1.5 text-xs font-semibold text-white shadow-soft transition-all hover:shadow-glow"
      >
        Sign in
      </Link>
    );
  }

  const initial = (user.email?.[0] ?? "U").toUpperCase();

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-full border border-ink-200/70 bg-white py-1 pl-1 pr-3 text-xs font-medium text-ink-800 shadow-sm transition-colors hover:bg-ink-50/70"
      >
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br from-brand-500 to-accent-500 text-[11px] font-semibold text-white">
          {initial}
        </span>
        <span className="hidden max-w-[8rem] truncate sm:inline">{user.email}</span>
        <ChevronDown size={13} className="text-ink-400" />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-2 w-64 origin-top-right animate-fade-up rounded-2xl border border-ink-200/70 bg-white p-2 shadow-elevated"
        >
          <div className="rounded-xl bg-gradient-to-br from-brand-50 via-white to-accent-50 p-3">
            <p className="text-xs font-semibold text-ink-900">{user.email}</p>
            <div className="mt-1 flex items-center gap-2">
              <span className="rounded-md bg-white px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-brand-700 ring-1 ring-brand-200">
                {user.role || "user"}
              </span>
              <span className="text-[10px] text-ink-500">{user.company_name || "Tenant"}</span>
            </div>
          </div>
          <div className="my-1 h-px bg-ink-100" />
          <Link
            href="/config/statutory"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-xs font-medium text-ink-700 transition-colors hover:bg-ink-50"
          >
            <Settings2 size={14} className="text-ink-400" />
            Statutory settings
          </Link>
          <Link
            href="/config/rules"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-xs font-medium text-ink-700 transition-colors hover:bg-ink-50"
          >
            <Ban size={14} className="text-ink-400" />
            Rule preferences
          </Link>
          <div className="my-1 h-px bg-ink-100" />
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              void logout();
            }}
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-xs font-medium text-danger-600 transition-colors hover:bg-danger-50"
          >
            <LogOut size={14} />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const groups = useNavGroups();
  const [mobileOpen, setMobileOpen] = useState(false);

  const allItems = groups.flatMap((g) => g.items);
  const currentItem = allItems.find(
    (i) => pathname === i.href || (i.href !== "/dashboard" && pathname.startsWith(i.href)),
  );
  const pageTitle = currentItem?.label ?? "Workspace";

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--bg-canvas)]">
      <aside className="hidden w-[15.5rem] flex-shrink-0 lg:flex lg:flex-col xl:w-[16.5rem]">
        <Sidebar groups={groups} />
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-50 flex lg:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-ink-950/60 backdrop-blur-sm"
            aria-label="Close menu overlay"
            onClick={() => setMobileOpen(false)}
          />
          <div className="relative h-full w-[min(280px,86vw)] flex-shrink-0 shadow-2xl">
            <Sidebar groups={groups} onClose={() => setMobileOpen(false)} />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="sticky top-0 z-40 flex-shrink-0 border-b border-ink-200/60 bg-white/85 backdrop-blur-md supports-[backdrop-filter]:bg-white/70">
          <div className="flex h-14 w-full items-center gap-3 px-4 sm:px-6 lg:gap-5">
            <button
              type="button"
              onClick={() => setMobileOpen(true)}
              className="rounded-lg p-2 text-ink-500 transition-colors hover:bg-ink-100 hover:text-ink-900 lg:hidden"
              aria-label="Open navigation"
            >
              <Menu size={20} />
            </button>

            <nav className="hidden min-w-0 items-center gap-1.5 text-sm md:flex">
              <Link
                href="/dashboard"
                className="truncate text-xs font-semibold text-ink-400 transition-colors hover:text-ink-700"
              >
                Workspace
              </Link>
              <ChevronRight size={13} className="flex-shrink-0 text-ink-300" aria-hidden />
              <span className="truncate text-xs font-semibold text-ink-900">{pageTitle}</span>
            </nav>

            <div className="hidden min-w-0 flex-1 lg:flex lg:justify-center">
              <button
                type="button"
                className="group inline-flex w-full max-w-md items-center gap-2.5 rounded-xl border border-ink-200/70 bg-ink-50/60 px-3.5 py-2 text-xs text-ink-500 shadow-sm transition-colors hover:border-brand-300 hover:bg-white"
              >
                <Search size={14} className="text-ink-400 group-hover:text-brand-600" />
                <span className="flex-1 text-left">Search anything…</span>
                <kbd className="hidden items-center gap-0.5 rounded-md border border-ink-200 bg-white px-1.5 py-0.5 text-[10px] font-medium text-ink-500 sm:inline-flex">
                  <Command size={10} /> K
                </kbd>
              </button>
            </div>

            <div className="ml-auto flex items-center gap-2">
              <button
                type="button"
                className="hidden rounded-lg border border-ink-200/70 bg-white p-2 text-ink-500 transition-colors hover:bg-ink-50 hover:text-ink-900 sm:inline-flex"
                aria-label="Notifications"
              >
                <Bell size={15} strokeWidth={2} />
              </button>
              <ProfileMenu />
            </div>
          </div>
        </header>

        <main className="scrollbar-thin flex-1 overflow-y-auto">
          <div className="mx-auto max-w-7xl animate-fade-in px-5 py-7 sm:px-8 lg:px-10 lg:py-9">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
