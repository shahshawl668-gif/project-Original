"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
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
  Landmark,
  LogOut,
  Shield,
  Search,
  Bell,
  Sparkles,
  ShieldCheck,
  ChevronDown,
  Building2,
  Command,
  IndianRupee,
  FileDown,
  ScrollText,
  Target,
  Scale,
  UserPlus,
  KeyRound,
  CalendarDays,
  Banknote,
  BookOpen,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/context/AuthContext";
import { ApiHealthBadge } from "@/components/ApiHealthBadge";
import { EntitySwitcher } from "@/components/EntitySwitcher";
import { PageTransition } from "@/components/motion/PageTransition";
import { SupportBanner } from "@/components/SupportBanner";

/**
 * Six boxes, not twenty-five links.
 *
 * Everything used to be listed at once, which made the sidebar a wall of text
 * where the four things anyone does daily were indistinguishable from the
 * twenty they configure once. Each group is now a box that opens, and only the
 * one you are working in is open.
 *
 * The grouping follows how a month is actually worked — run the payroll, check
 * the attendance behind it, reconcile what left the bank and what hit the
 * ledger — rather than how the code is organised.
 */
const navGroups = [
  {
    label: "Payroll",
    icon: UploadCloud,
    blurb: "Registers, results and CTC",
    items: [
      { href: "/payroll/upload", label: "Upload & validate", icon: UploadCloud },
      { href: "/payroll/results", label: "Results", icon: ClipboardCheck },
      { href: "/payroll/history", label: "Register history", icon: History },
      { href: "/ctc/upload", label: "Upload CTC", icon: FileSpreadsheet },
      { href: "/ctc/history", label: "CTC history", icon: FolderArchive },
      { href: "/budget/upload", label: "Upload budget", icon: Target },
    ],
  },
  {
    label: "Attendance",
    icon: CalendarDays,
    blurb: "Days worked, days paid",
    items: [
      { href: "/payroll/attendance", label: "Attendance register", icon: CalendarDays },
    ],
  },
  {
    label: "Bank & JV",
    icon: Scale,
    blurb: "Payments and the ledger",
    items: [
      { href: "/reconciliation", label: "Month close", icon: Scale },
      { href: "/reconciliation/bank", label: "Bank payments", icon: Banknote },
      { href: "/reconciliation/jv", label: "Journal voucher", icon: BookOpen },
    ],
  },
  {
    label: "Insights",
    icon: BarChart3,
    blurb: "Cost and reporting",
    items: [
      { href: "/cost", label: "Cost analysis", icon: IndianRupee },
      { href: "/reports", label: "Reports", icon: FileDown },
    ],
  },
  {
    label: "Settings",
    icon: Settings2,
    blurb: "Rules, people and history",
    items: [
      { href: "/config/statutory", label: "Statutory engine", icon: Settings2 },
      { href: "/config/tax", label: "Income tax & thresholds", icon: Landmark },
      { href: "/config/components", label: "Salary components", icon: Layers },
      { href: "/config/bank-profiles", label: "Bank file profiles", icon: Banknote },
      { href: "/config/jv-templates", label: "JV templates", icon: BookOpen },
      { href: "/config/rules", label: "Rule suppressions", icon: Ban },
      { href: "/rule-engine/formula", label: "Formulas", icon: Code2 },
      { href: "/rule-engine/slabs", label: "PT / LWF slabs", icon: BarChart3 },
      { href: "/config/team", label: "Team & invitations", icon: UserPlus },
      { href: "/audit", label: "Audit trail", icon: ScrollText },
    ],
  },
];

function useNavGroups() {
  const { user } = useAuth();
  return useMemo(() => {
    return navGroups.map((g) => {
      if (g.label !== "Settings") return g;
      const adminItems =
        user?.role === "admin"
          ? [
              { href: "/admin/users", label: "Users & roles", icon: Shield },
              { href: "/admin/support", label: "Support access", icon: KeyRound },
            ]
          : [];
      return { ...g, items: [...g.items, ...adminItems] };
    });
  }, [user?.role]);
}

function isActiveHref(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** One collapsible box. Opens itself when you are somewhere inside it. */
function NavGroup({
  group,
  onNavigate,
}: {
  group: ReturnType<typeof useNavGroups>[number];
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const holdsCurrentPage = group.items.some((i) => isActiveHref(pathname, i.href));
  // `null` means "nobody has clicked yet", so the route decides. Once someone
  // clicks, their choice wins until they navigate into a different box.
  const [manual, setManual] = useState<boolean | null>(null);
  const open = manual ?? holdsCurrentPage;
  const GroupIcon = group.icon;

  useEffect(() => {
    setManual(null);
  }, [holdsCurrentPage]);

  return (
    <div
      className={`overflow-hidden rounded-xl border transition-colors ${
        open || holdsCurrentPage
          ? "border-brand-200 bg-brand-50/50"
          : "border-ink-200/70 bg-white hover:border-brand-200"
      }`}
    >
      <button
        type="button"
        onClick={() => setManual(!open)}
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left"
      >
        <span
          className={`flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg ${
            holdsCurrentPage ? "bg-brand-600 text-white" : "bg-brand-100 text-brand-700"
          }`}
        >
          <GroupIcon size={15} strokeWidth={2} aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-semibold text-ink-800">
            {group.label}
          </span>
          <span className="block truncate text-[10.5px] text-ink-500">{group.blurb}</span>
        </span>
        <ChevronDown
          size={15}
          aria-hidden
          className={`flex-shrink-0 text-ink-400 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div className="space-y-0.5 border-t border-brand-100 px-2 pb-2 pt-2">
          {group.items.map((item) => {
            const Icon = item.icon;
            const active = isActiveHref(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onNavigate}
                aria-current={active ? "page" : undefined}
                className={`group flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[12.5px] transition-colors ${
                  active
                    ? "bg-brand-600 font-semibold text-white"
                    : "text-ink-600 hover:bg-brand-100/70 hover:text-ink-900"
                }`}
              >
                <Icon
                  size={14}
                  strokeWidth={active ? 2.2 : 1.9}
                  aria-hidden
                  className={`flex-shrink-0 ${active ? "text-white" : "text-ink-400 group-hover:text-brand-700"}`}
                />
                <span className="truncate">{item.label}</span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Sidebar({
  groups,
  onClose,
}: {
  groups: ReturnType<typeof useNavGroups>;
  onClose?: () => void;
}) {
  const pathname = usePathname();
  const homeActive = pathname === "/dashboard";

  return (
    <div className="flex h-full flex-col overflow-hidden border-r border-ink-200/80 bg-white">
      <div className="flex items-center justify-between gap-3 px-4 pb-4 pt-5">
        <Link href="/dashboard" className="flex min-w-0 items-center gap-2.5" onClick={onClose}>
          <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 shadow-[0_6px_20px_-6px_rgba(2,132,199,0.6)]">
            <ShieldCheck size={17} className="text-white" strokeWidth={2.25} aria-hidden />
          </span>
          <span className="min-w-0">
            <span className="block text-[15px] font-bold leading-tight tracking-tight text-ink-900">
              PayrollCheck
            </span>
            <span className="mt-0.5 block truncate text-[9.5px] font-semibold uppercase tracking-[0.18em] text-brand-700">
              India · Audit grade
            </span>
          </span>
        </Link>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-ink-500 transition-colors hover:bg-ink-100 hover:text-ink-900 lg:hidden"
            aria-label="Close menu"
          >
            <X size={18} />
          </button>
        )}
      </div>

      <nav className="scrollbar-thin flex-1 space-y-2 overflow-y-auto px-3 pb-6">
        <Link
          href="/dashboard"
          onClick={onClose}
          aria-current={homeActive ? "page" : undefined}
          className={`flex items-center gap-2.5 rounded-xl border px-3 py-2.5 transition-colors ${
            homeActive
              ? "border-brand-600 bg-brand-600 text-white"
              : "border-ink-200/70 bg-white text-ink-800 hover:border-brand-200 hover:bg-brand-50"
          }`}
        >
          <span
            className={`flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg ${
              homeActive ? "bg-white/20 text-white" : "bg-brand-100 text-brand-700"
            }`}
          >
            <Building2 size={15} strokeWidth={2} aria-hidden />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[13px] font-semibold">Companies</span>
            <span
              className={`block truncate text-[10.5px] ${homeActive ? "text-white/75" : "text-ink-500"}`}
            >
              Your group at a glance
            </span>
          </span>
        </Link>

        {groups.map((group) => (
          <NavGroup key={group.label} group={group} onNavigate={onClose} />
        ))}
      </nav>

      <div className="border-t border-ink-200/80 px-4 py-3">
        <ApiHealthBadge />
      </div>
    </div>
  );
}

function ProfileMenu() {
  const { user, isAuthenticated, logout } = useAuth();
  const router = useRouter();
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
        className="flex items-center gap-2 rounded-full border border-ink-200/70 bg-white py-1 pl-1 pr-3 text-xs font-medium text-ink-800 shadow-sm transition-colors hover:bg-ink-50/70 dark:border-white/10 dark:bg-white/[0.04] dark:text-ink-100 dark:hover:bg-white/[0.08]"
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
          className="absolute right-0 top-full z-50 mt-2 w-64 origin-top-right animate-fade-up rounded-2xl border border-ink-200/70 bg-white p-2 shadow-elevated dark:border-white/10 dark:bg-ink-900"
        >
          <div className="rounded-xl bg-gradient-to-br from-brand-50 via-white to-accent-50 p-3 dark:from-brand-500/10 dark:via-ink-900 dark:to-accent-500/10">
            <p className="text-xs font-semibold text-ink-900 dark:text-white">{user.email}</p>
            <div className="mt-1 flex items-center gap-2">
              <span className="rounded-md bg-white px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-brand-700 ring-1 ring-brand-200 dark:bg-white/10 dark:text-brand-300 dark:ring-brand-500/30">
                {user.role || "user"}
              </span>
              <span className="text-[10px] text-ink-500 dark:text-ink-300">
                {user.company_name || "Tenant"}
              </span>
            </div>
          </div>
          <div className="my-1 h-px bg-ink-100 dark:bg-white/10" />
          <Link
            href="/config/statutory"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-xs font-medium text-ink-700 transition-colors hover:bg-ink-50 dark:text-ink-200 dark:hover:bg-white/[0.06]"
          >
            <Settings2 size={14} className="text-ink-400" />
            Statutory settings
          </Link>
          <Link
            href="/config/rules"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-xs font-medium text-ink-700 transition-colors hover:bg-ink-50 dark:text-ink-200 dark:hover:bg-white/[0.06]"
          >
            <Ban size={14} className="text-ink-400" />
            Rule preferences
          </Link>
          <div className="my-1 h-px bg-ink-100 dark:bg-white/10" />
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              void logout().finally(() => router.replace("/login"));
            }}
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-xs font-medium text-danger-600 transition-colors hover:bg-danger-50 dark:text-danger-400 dark:hover:bg-danger-500/10"
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

  // The home page is not in any group, so it needs naming here or the
  // breadcrumb falls back to its own parent and reads "Workspace › Workspace".
  const allItems = groups.flatMap((g) => g.items);
  const currentItem = allItems.find((i) => isActiveHref(pathname, i.href));
  const pageTitle =
    pathname === "/dashboard" ? "Companies" : (currentItem?.label ?? "Workspace");

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
        <header className="sticky top-0 z-40 flex-shrink-0 border-b border-ink-200/60 bg-white/85 backdrop-blur-md supports-[backdrop-filter]:bg-white/70 dark:border-white/5 dark:bg-ink-950/85 dark:supports-[backdrop-filter]:bg-ink-950/65">
          <div className="flex h-14 w-full items-center gap-3 px-4 sm:px-6 lg:gap-5">
            <button
              type="button"
              onClick={() => setMobileOpen(true)}
              className="rounded-lg p-2 text-ink-500 transition-colors hover:bg-ink-100 hover:text-ink-900 dark:text-ink-300 dark:hover:bg-white/[0.06] dark:hover:text-white lg:hidden"
              aria-label="Open navigation"
            >
              <Menu size={20} />
            </button>

            <nav className="hidden min-w-0 items-center gap-1.5 text-sm md:flex">
              <Link
                href="/dashboard"
                className="truncate text-xs font-semibold text-ink-400 transition-colors hover:text-ink-700 dark:text-ink-400 dark:hover:text-white"
              >
                Workspace
              </Link>
              <ChevronRight size={13} className="flex-shrink-0 text-ink-300 dark:text-ink-500" aria-hidden />
              <span className="truncate text-xs font-semibold text-ink-900 dark:text-white">
                {pageTitle}
              </span>
            </nav>

            <div className="hidden min-w-0 flex-1 lg:flex" />

            <div className="ml-auto flex items-center gap-2">
              <EntitySwitcher />
              <ProfileMenu />
            </div>
          </div>
        </header>

        <SupportBanner />

        <main className="scrollbar-thin flex-1 overflow-y-auto">
          <div className="mx-auto max-w-7xl px-5 py-7 sm:px-8 lg:px-10 lg:py-9">
            <PageTransition>{children}</PageTransition>
          </div>
        </main>
      </div>
    </div>
  );
}
