"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ChevronDown, ChevronRight, Loader2, LogOut, Menu, ShieldCheck, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/context/AuthContext";
import { useEntity } from "@/context/EntityContext";
import { PRODUCT_NAME, PRODUCT_TAGLINE } from "@/lib/brand";
import { ADMIN_ITEMS, NAV_GROUPS, breadcrumbsFor, isActiveHref, type NavGroup } from "@/lib/navigation";
import { ApiHealthBadge } from "@/components/ApiHealthBadge";
import { EntitySwitcher } from "@/components/EntitySwitcher";
import { NotificationBell } from "@/components/NotificationBell";
import { noteNavigation } from "@/components/layout/BackLink";
import { ContextBar } from "@/components/layout/ContextBar";
import { PageTransition } from "@/components/motion/PageTransition";
import { SupportBanner } from "@/components/SupportBanner";
import { cn } from "@/lib/utils";

/**
 * Navigation is grouped by the job at hand — see the month, bring data in,
 * check it, close it, understand it, report, connect systems, configure — and
 * is defined once in `lib/navigation.ts`.
 *
 * Small groups are always open: a menu of eight headings with two or three
 * links each reads faster than eight closed boxes. The two large groups
 * (Studio and Configuration) collapse unless you are inside them.
 */
function useNavGroups(): NavGroup[] {
  const { user } = useAuth();
  const { activeRole } = useEntity();
  return useMemo(() => {
    // Studio is a technical workspace (analyst and above); a viewer would
    // only meet a refusal there, so it is not offered.
    const groups = activeRole === "viewer" ? NAV_GROUPS.filter((g) => g.id !== "studio") : NAV_GROUPS;
    return groups.map((g) =>
      g.id === "config" && user?.role === "admin" ? { ...g, items: [...g.items, ...ADMIN_ITEMS] } : g,
    );
  }, [user?.role, activeRole]);
}

function NavSection({ group, onNavigate }: { group: NavGroup; onNavigate?: () => void }) {
  const pathname = usePathname();
  const holdsCurrentPage = group.items.some((i) => isActiveHref(pathname, i.href));
  const [manual, setManual] = useState<boolean | null>(null);
  const open = !group.collapsible || (manual ?? holdsCurrentPage);
  useEffect(() => setManual(null), [holdsCurrentPage]);
  const listId = `nav-${group.id}`;

  return (
    <div className="pt-3 first:pt-1">
      {group.collapsible ? (
        <button
          type="button"
          onClick={() => setManual(!open)}
          aria-expanded={open}
          aria-controls={listId}
          className="flex w-full items-center gap-1 rounded-md px-2.5 py-1 text-left text-[11px] font-semibold uppercase tracking-[0.04em] text-ink-500 transition-colors hover:text-ink-800"
        >
          <span className="flex-1 truncate">{group.label}</span>
          <ChevronDown size={13} aria-hidden className={cn("flex-shrink-0 transition-transform", open ? "" : "-rotate-90")} />
        </button>
      ) : (
        <p className="px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.04em] text-ink-500">{group.label}</p>
      )}
      {open && (
        <ul id={listId} className="mt-0.5 space-y-px">
          {group.items.map((item) => {
            const Icon = item.icon;
            const active = isActiveHref(pathname, item.href);
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "group flex items-center gap-2.5 rounded-md px-2.5 py-[5px] text-[13px] transition-colors duration-fast",
                    active ? "bg-brand-50 font-medium text-brand-800" : "text-ink-700 hover:bg-ink-100 hover:text-ink-900",
                  )}
                >
                  <Icon
                    size={15}
                    strokeWidth={active ? 2.1 : 1.8}
                    aria-hidden
                    className={cn("flex-shrink-0", active ? "text-brand-600" : "text-ink-500 group-hover:text-ink-600")}
                  />
                  <span className="truncate">{item.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function BrandMark({ onClick }: { onClick?: () => void }) {
  return (
    <Link href="/control-centre" className="flex min-w-0 items-center gap-2" onClick={onClick}>
      <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg bg-brand-600">
        <ShieldCheck size={15} className="text-white" strokeWidth={2.25} aria-hidden />
      </span>
      <span className="min-w-0">
        <span className="block text-[14px] font-semibold leading-tight tracking-tight text-ink-900">{PRODUCT_NAME}</span>
        <span className="block truncate text-[10.5px] leading-tight text-ink-500">{PRODUCT_TAGLINE}</span>
      </span>
    </Link>
  );
}

function Sidebar({ groups, onClose }: { groups: NavGroup[]; onClose?: () => void }) {
  return (
    <div className="flex h-full flex-col overflow-hidden border-r border-ink-200 bg-white">
      <div className="flex h-14 flex-shrink-0 items-center justify-between gap-3 border-b border-ink-100 px-4">
        <BrandMark onClick={onClose} />
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-ink-500 transition-colors hover:bg-ink-100 hover:text-ink-900 lg:hidden"
            aria-label="Close menu"
          >
            <X size={18} />
          </button>
        )}
      </div>
      <nav aria-label="Main" className="scrollbar-thin flex-1 overflow-y-auto px-2 pb-6 pt-2">
        {groups.map((group) => (
          <NavSection key={group.id} group={group} onNavigate={onClose} />
        ))}
      </nav>
      <div className="border-t border-ink-100 px-3 py-2.5">
        <ApiHealthBadge />
      </div>
    </div>
  );
}

function ProfileMenu() {
  const { user, isAuthenticated, logout } = useAuth();
  const { activeRole } = useEntity();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!isAuthenticated || !user) {
    return (
      <Link href="/login" className="inline-flex h-8 items-center rounded-lg bg-brand-600 px-3 text-xs font-medium text-white hover:bg-brand-700">
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
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account: ${user.email}`}
        className="flex h-8 items-center gap-1.5 rounded-full py-0.5 pl-0.5 pr-1.5 text-ink-700 transition-colors hover:bg-ink-100"
      >
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-ink-800 text-[11px] font-semibold text-white">{initial}</span>
        <ChevronDown size={13} className="text-ink-500" aria-hidden />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 top-full z-50 mt-1.5 w-64 animate-fade-up rounded-xl border border-ink-200 bg-white p-1 shadow-elevated">
          <div className="px-3 py-2.5">
            <p className="truncate text-[13px] font-medium text-ink-900">{user.email}</p>
            <p className="mt-0.5 text-xs text-ink-500">
              {activeRole ? <span className="capitalize">{activeRole}</span> : (user.role || "user")}
              {user.company_name ? ` · ${user.company_name}` : ""}
            </p>
          </div>
          <div className="my-1 h-px bg-ink-100" />
          <Link
            role="menuitem"
            href="/config/team"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] text-ink-700 transition-colors hover:bg-ink-50"
          >
            Team & invitations
          </Link>
          <Link
            role="menuitem"
            href="/audit"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] text-ink-700 transition-colors hover:bg-ink-50"
          >
            Audit trail
          </Link>
          <div className="my-1 h-px bg-ink-100" />
          <button
            role="menuitem"
            type="button"
            onClick={() => {
              setOpen(false);
              void logout().finally(() => router.replace("/login"));
            }}
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] text-danger-700 transition-colors hover:bg-danger-50"
          >
            <LogOut size={14} aria-hidden />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * The mark on its own, for anyone the product does not yet know.
 *
 * Signed out, there is nothing to navigate until there is an account, so
 * there is no navigation — a menu that cannot load anything only makes a
 * visitor guess which part is broken.
 */
function BrandFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-[var(--bg-canvas)]">
      <header className="flex-shrink-0 border-b border-ink-200 bg-white">
        <div className="mx-auto flex h-14 w-full max-w-5xl items-center justify-between gap-4 px-5 sm:px-8">
          <Link href="/" className="flex min-w-0 items-center gap-2">
            <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg bg-brand-600">
              <ShieldCheck size={15} className="text-white" strokeWidth={2.25} aria-hidden />
            </span>
            <span className="text-[14px] font-semibold tracking-tight text-ink-900">{PRODUCT_NAME}</span>
          </Link>
          <Link href="/login" className="inline-flex h-8 items-center rounded-lg bg-brand-600 px-3.5 text-xs font-medium text-white transition-colors hover:bg-brand-700">
            Sign in
          </Link>
        </div>
      </header>
      <main className="flex flex-1 items-center justify-center px-5 py-12">{children}</main>
    </div>
  );
}

function Breadcrumbs({ groups }: { groups: NavGroup[] }) {
  const pathname = usePathname();
  const crumbs = breadcrumbsFor(pathname, groups);
  return (
    <nav aria-label="Breadcrumb" className="hidden min-w-0 md:block">
      <ol className="flex min-w-0 items-center gap-1 text-[13px]">
        {crumbs.map((c, i) => {
          const last = i === crumbs.length - 1;
          return (
            <li key={`${c.label}-${i}`} className="flex min-w-0 items-center gap-1">
              {i > 0 ? <ChevronRight size={13} className="flex-shrink-0 text-ink-300" aria-hidden /> : null}
              {last || !c.href ? (
                <span aria-current={last ? "page" : undefined} className={cn("truncate", last ? "font-medium text-ink-900" : "text-ink-500")}>
                  {c.label}
                </span>
              ) : (
                <Link href={c.href} className="truncate text-ink-500 transition-colors hover:text-ink-900">
                  {c.label}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const groups = useNavGroups();
  const [mobileOpen, setMobileOpen] = useState(false);
  const { isAuthenticated, loading: authLoading } = useAuth();
  const { generation } = useEntity();
  const mainRef = useRef<HTMLElement>(null);
  const positions = useRef(new Map<string, number>());
  const popped = useRef(false);

  useEffect(() => {
    const onPop = () => { popped.current = true; };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // The scroll container is <main>, not the window, so the browser cannot
  // restore it. A new page starts at the top; going back returns to where the
  // reader was — waiting for the page to be tall enough, since its data may
  // still be arriving.
  useEffect(() => {
    noteNavigation();
    setMobileOpen(false);
    const main = mainRef.current;
    if (!main) return;
    const key = window.location.pathname + window.location.search;
    const target = popped.current ? positions.current.get(key) ?? 0 : 0;
    popped.current = false;
    let tries = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const attempt = () => {
      if (target === 0 || main.scrollHeight - main.clientHeight >= target || tries++ > 20) {
        main.scrollTo({ top: target });
        return;
      }
      timer = setTimeout(attempt, 100);
    };
    attempt();
    return () => clearTimeout(timer);
  }, [pathname]);

  if (authLoading) {
    return (
      <BrandFrame>
        <p className="flex items-center gap-2 text-sm text-ink-500">
          <Loader2 size={15} className="animate-spin" aria-hidden />
          Checking your session…
        </p>
      </BrandFrame>
    );
  }

  if (!isAuthenticated) {
    return (
      <BrandFrame>
        <div className="w-full max-w-md rounded-xl border border-ink-200 bg-white p-8 text-center shadow-soft">
          <h1 className="text-lg font-semibold tracking-tight text-ink-900">Sign in to continue</h1>
          <p className="mt-2 text-sm leading-relaxed text-ink-600">
            {PRODUCT_NAME} holds payroll data, so nothing is shown until we know who you are.
          </p>
          <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-center">
            <Link
              href="/login"
              className="inline-flex h-9 items-center justify-center rounded-lg bg-brand-600 px-5 text-sm font-medium text-white transition-colors hover:bg-brand-700"
            >
              Sign in
            </Link>
          </div>
        </div>
      </BrandFrame>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--bg-canvas)]">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[70] focus:rounded-lg focus:bg-white focus:px-3 focus:py-2 focus:text-sm focus:shadow-elevated"
      >
        Skip to content
      </a>
      <aside className="hidden w-60 flex-shrink-0 lg:flex lg:flex-col">
        <Sidebar groups={groups} />
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-50 flex lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <button
            type="button"
            className="absolute inset-0 animate-fade-in bg-ink-950/30"
            aria-label="Close menu"
            onClick={() => setMobileOpen(false)}
          />
          <div className="relative h-full w-[min(288px,86vw)] flex-shrink-0 animate-slide-in shadow-elevated">
            <Sidebar groups={groups} onClose={() => setMobileOpen(false)} />
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="z-40 flex-shrink-0 border-b border-ink-200 bg-white">
          <div className="flex h-14 w-full items-center gap-2 px-3 sm:px-5 lg:gap-4">
            <button
              type="button"
              onClick={() => setMobileOpen(true)}
              className="rounded-md p-1.5 text-ink-600 transition-colors hover:bg-ink-100 hover:text-ink-900 lg:hidden"
              aria-label="Open navigation"
            >
              <Menu size={20} />
            </button>
            <Breadcrumbs groups={groups} />
            <div className="ml-auto flex min-w-0 items-center gap-1.5 sm:gap-2">
              <EntitySwitcher />
              <ContextBar />
              <span className="mx-0.5 hidden h-5 w-px bg-ink-200 sm:block" aria-hidden />
              <NotificationBell />
              <ProfileMenu />
            </div>
          </div>
        </header>

        <SupportBanner />

        <main
          id="main"
          ref={mainRef}
          tabIndex={-1}
          className="scrollbar-thin flex-1 overflow-y-auto outline-none"
          onScroll={(e) => positions.current.set(window.location.pathname + window.location.search, e.currentTarget.scrollTop)}
        >
          <div className="mx-auto w-full max-w-[1440px] px-4 py-5 sm:px-6 lg:px-8 lg:py-6">
            {/* Keyed on the company generation: a switch remounts the page, so
                no filter or selection from the last company survives. */}
            <PageTransition key={generation}>{children}</PageTransition>
          </div>
        </main>
      </div>
    </div>
  );
}
