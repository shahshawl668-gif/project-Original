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
  Ban,
  LogIn,
  LogOut,
  Shield,
  Search,
  Bell,
  HelpCircle,
} from "lucide-react";
import { useMemo, useState } from "react";

import { useAuth } from "@/context/AuthContext";

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
      { href: "/config/rules", label: "Rule suppressions", icon: Ban },
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

function SidebarContent({
  groups,
  onClose,
}: {
  groups: ReturnType<typeof useNavGroups>;
  onClose?: () => void;
}) {
  const pathname = usePathname();

  return (
    <div className="flex h-full flex-col border-r border-slate-200/80 bg-white">
      <div className="flex items-center justify-between gap-3 px-4 py-5">
        <Link
          href="/dashboard"
          className="flex min-w-0 items-center gap-3"
          onClick={onClose}
        >
          <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 shadow-soft">
            <Building2 size={18} className="text-white" aria-hidden />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold leading-tight text-slate-900">PayrollCheck</p>
            <p className="mt-0.5 truncate text-2xs font-medium uppercase tracking-wider text-slate-500">
              India payroll audit
            </p>
          </div>
        </Link>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 lg:hidden"
            aria-label="Close menu"
          >
            <X size={18} />
          </button>
        )}
      </div>

      <nav className="scrollbar-thin flex-1 space-y-6 overflow-y-auto px-3 pb-6">
        {groups.map((group) => (
          <div key={group.label}>
            <p className="mb-2 px-3 text-2xs font-semibold uppercase tracking-widest text-slate-400">
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
                    className={`group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all ${
                      active
                        ? "bg-brand-50 text-brand-800 shadow-sm ring-1 ring-brand-600/15"
                        : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                    }`}
                  >
                    <Icon
                      size={17}
                      strokeWidth={active ? 2.25 : 2}
                      className={`flex-shrink-0 ${active ? "text-brand-600" : "text-slate-400 group-hover:text-slate-600"}`}
                    />
                    <span className="truncate">{item.label}</span>
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className="border-t border-slate-100 px-4 py-4">
        <p className="text-2xs leading-relaxed text-slate-400">
          Statutory validation aligned with your tenant configuration — PF, ESIC, PT, LWF.
        </p>
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const groups = useNavGroups();
  const [mobileOpen, setMobileOpen] = useState(false);
  const { user, loading: authLoading, logout, isAuthenticated } = useAuth();

  const allItems = groups.flatMap((g) => g.items);
  const currentItem = allItems.find(
    (i) => pathname === i.href || (i.href !== "/dashboard" && pathname.startsWith(i.href)),
  );
  const pageTitle = currentItem?.label ?? "Workspace";

  return (
    <div className="flex h-screen overflow-hidden bg-[#f6f8fc]">
      <aside className="hidden w-60 flex-shrink-0 lg:flex lg:flex-col xl:w-[17rem]">
        <SidebarContent groups={groups} />
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-50 flex lg:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-slate-900/40 backdrop-blur-[2px]"
            aria-label="Close menu overlay"
            onClick={() => setMobileOpen(false)}
          />
          <div className="relative h-full w-[min(280px,88vw)] flex-shrink-0 bg-white shadow-2xl">
            <SidebarContent groups={groups} onClose={() => setMobileOpen(false)} />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="sticky top-0 z-40 flex-shrink-0 border-b border-slate-200/80 bg-white/90 shadow-sm backdrop-blur-md supports-[backdrop-filter]:bg-white/75">
          <div className="flex h-[3.75rem] w-full items-center gap-3 px-4 sm:px-6 lg:gap-6">
            <button
              type="button"
              onClick={() => setMobileOpen(true)}
              className="rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 lg:hidden"
              aria-label="Open navigation"
            >
              <Menu size={20} />
            </button>

            <nav className="hidden min-w-0 items-center gap-1 text-sm text-slate-500 md:flex lg:gap-1.5">
              <Link
                href="/dashboard"
                className="truncate font-medium text-slate-400 transition-colors hover:text-slate-700"
              >
                Home
              </Link>
              <ChevronRight size={14} className="flex-shrink-0 text-slate-300" aria-hidden />
              <span className="truncate font-semibold text-slate-900">{pageTitle}</span>
            </nav>

            <div className="hidden min-w-0 flex-1 lg:flex lg:justify-center">
              <div className="relative w-full max-w-lg">
                <Search
                  className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
                  aria-hidden
                />
                <input
                  type="search"
                  placeholder="Search pages, shortcuts…"
                  readOnly
                  className="h-10 w-full cursor-default rounded-xl border border-slate-200/90 bg-slate-50/80 py-2 pl-10 pr-4 text-sm text-slate-500 placeholder:text-slate-400 outline-none ring-brand-500/20 transition-shadow focus-visible:ring-[3px]"
                />
              </div>
            </div>

            <div className="ml-auto flex items-center gap-1 sm:gap-2">
              <button
                type="button"
                className="hidden rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-800 md:inline-flex"
                aria-label="Notifications"
              >
                <Bell size={18} strokeWidth={1.75} />
              </button>
              <button
                type="button"
                className="hidden rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-800 md:inline-flex"
                aria-label="Help"
              >
                <HelpCircle size={18} strokeWidth={1.75} />
              </button>

              <div className="hidden h-6 w-px bg-slate-200 sm:block" aria-hidden />

              {!authLoading && isAuthenticated && user && (
                <span className="hidden max-w-[10rem] truncate text-xs text-slate-600 sm:inline">
                  {user.email}
                  {user.role === "admin" ? (
                    <span className="ml-1.5 rounded-md bg-brand-50 px-1.5 py-0.5 text-2xs font-semibold uppercase text-brand-700">
                      admin
                    </span>
                  ) : null}
                </span>
              )}
              {!authLoading && !isAuthenticated && (
                <span className="hidden text-xs text-slate-500 sm:inline">Guest</span>
              )}
              {!authLoading && isAuthenticated ? (
                <button
                  type="button"
                  onClick={() => void logout()}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm transition-colors hover:bg-slate-50"
                >
                  <LogOut size={14} strokeWidth={2} />
                  <span className="hidden sm:inline">Sign out</span>
                </button>
              ) : (
                <Link
                  href="/login"
                  className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-1.5 text-xs font-semibold text-white shadow-soft transition-colors hover:bg-brand-700"
                >
                  <LogIn size={14} strokeWidth={2} /> Sign in
                </Link>
              )}
            </div>
          </div>
          <div className="flex border-t border-slate-100 px-4 py-1.5 text-xs md:hidden">
            <span className="font-semibold text-slate-900">{pageTitle}</span>
          </div>
        </header>

        <main className="scrollbar-thin flex-1 overflow-y-auto">
          <div className="mx-auto max-w-7xl px-5 py-8 sm:px-8 lg:px-10 lg:py-10">{children}</div>
        </main>
      </div>
    </div>
  );
}
