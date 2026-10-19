/**
 * The product's navigation, grouped by the job being done rather than by how
 * the code is organised: see the month, bring data in, check it, close it,
 * understand it, report on it, connect systems, configure.
 *
 * Every route a signed-in person can reach from the menu is listed here once.
 * Pages reached from another page (a run, an employee, a release) name their
 * parent in DETAIL_ROUTES so the breadcrumb and the menu highlight still know
 * where they are.
 */
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  Ban,
  Building2,
  CalendarDays,
  Cable,
  ClipboardCheck,
  Code2,
  FileBarChart,
  FileDown,
  FileSpreadsheet,
  FolderArchive,
  GitBranch,
  Gauge,
  History,
  IndianRupee,
  KeyRound,
  Landmark,
  Layers,
  ListTodo,
  Loader,
  PlugZap,
  Scale,
  ScrollText,
  Settings2,
  Shield,
  Shuffle,
  UploadCloud,
  UserPlus,
  Users,
  Webhook,
  Workflow,
} from "lucide-react";

/**
 * Which modules the menu shows. Validation — the register, its checks, its
 * findings and the configuration that drives them — is always on. The rest are
 * kept in the code and reachable by URL, but not offered in the menu until they
 * are switched on:
 *
 *   NEXT_PUBLIC_ENABLED_MODULES=all                           everything
 *   NEXT_PUBLIC_ENABLED_MODULES=reports,studio                pick modules
 *   (unset)                                                   validation only
 *
 * Modules: reports, studio.
 * It is read at build time, so changing it means a rebuild.
 */
const ENABLED_MODULES = new Set(
  (process.env.NEXT_PUBLIC_ENABLED_MODULES ?? "").split(",").map((m) => m.trim()).filter(Boolean),
);
export const moduleEnabled = (module?: string): boolean =>
  !module || ENABLED_MODULES.has("all") || ENABLED_MODULES.has(module);

export type NavItem = { href: string; label: string; icon: LucideIcon; module?: string };
export type NavGroup = {
  id: string;
  label: string;
  items: NavItem[];
  /** Large groups collapse unless you are inside them. */
  collapsible?: boolean;
  module?: string;
};

const ALL_NAV_GROUPS: NavGroup[] = [
  {
    id: "overview",
    label: "Overview",
    items: [
      { href: "/control-centre", label: "Payroll Control Centre", icon: Gauge },
      { href: "/dashboard", label: "Companies", icon: Building2 },
    ],
  },
  {
    id: "data",
    label: "Data & imports",
    items: [
      { href: "/payroll/upload", label: "Salary register", icon: UploadCloud },
      { href: "/payroll/history", label: "Register history", icon: History },
      { href: "/payroll/attendance", label: "Attendance", icon: CalendarDays },
      { href: "/payroll/master", label: "Employee master", icon: Users },
      { href: "/ctc/upload", label: "CTC upload", icon: FileSpreadsheet },
      { href: "/ctc/history", label: "CTC history", icon: FolderArchive },
    ],
  },
  {
    id: "validation",
    label: "Validation & findings",
    items: [
      { href: "/payroll/validation", label: "Validation runs", icon: Loader },
      { href: "/payroll/results", label: "Results", icon: ClipboardCheck },
      { href: "/payroll/issues", label: "Issues", icon: ListTodo },
    ],
  },
  {
    id: "close",
    label: "Approval",
    items: [{ href: "/reconciliation", label: "Month approval", icon: Scale }],
  },
  {
    id: "reports",
    module: "reports",
    label: "Reports",
    items: [
      { href: "/reports", label: "Report Centre", icon: FileDown },
      { href: "/reports/builder", label: "Report Builder", icon: FileBarChart },
    ],
  },
  {
    id: "studio",
    module: "studio",
    label: "Studio",
    collapsible: true,
    items: [
      { href: "/studio", label: "Overview", icon: PlugZap },
      { href: "/studio/api", label: "API Centre", icon: KeyRound },
      { href: "/studio/connections", label: "Connections", icon: Cable },
      { href: "/studio/mapping", label: "Data mapping", icon: Shuffle },
      { href: "/studio/workflows", label: "Workflows", icon: Workflow },
      { href: "/studio/webhooks", label: "Webhooks", icon: Webhook },
      { href: "/studio/developer", label: "Developer", icon: Code2 },
      { href: "/studio/releases", label: "Releases", icon: GitBranch },
      { href: "/studio/runs", label: "Run history", icon: Activity },
    ],
  },
  {
    id: "setup-salary",
    label: "Salary & statutory",
    collapsible: true,
    items: [
      { href: "/config/components", label: "Salary components", icon: Layers },
      { href: "/config/statutory", label: "Statutory engine", icon: Settings2 },
      { href: "/config/tax", label: "Income tax & thresholds", icon: Landmark },
    ],
  },
  {
    id: "setup-rules",
    label: "Validation rules",
    collapsible: true,
    items: [
      { href: "/config/validation-matrix", label: "Validation matrix", icon: ClipboardCheck },
      { href: "/config/rules", label: "Rule suppressions", icon: Ban },
    ],
  },
  {
    id: "config",
    label: "Company & access",
    collapsible: true,
    items: [
      { href: "/config/companies", label: "Group companies", icon: Building2 },
      { href: "/config/team", label: "Team & invitations", icon: UserPlus },
      { href: "/config/upload", label: "Configuration upload", icon: FileSpreadsheet },
      { href: "/audit", label: "Audit trail", icon: ScrollText },
    ],
  },
];

export const NAV_GROUPS: NavGroup[] = ALL_NAV_GROUPS
  .filter((g) => moduleEnabled(g.module))
  .map((g) => ({ ...g, items: g.items.filter((i) => moduleEnabled(i.module)) }))
  .filter((g) => g.items.length > 0);

/**
 * The top bar: each entry is a menu holding one or more of the groups above, in
 * order. A menu with several groups shows them as a rail on the left of its
 * panel, the way Darwinbox's Spend menu shows Payroll Setup and Compensation Setup.
 */
export type MenuDef = { id: string; label: string; groups: string[] };
export const MENU_DEFS: MenuDef[] = [
  { id: "home", label: "Home", groups: ["overview"] },
  { id: "data", label: "Data & imports", groups: ["data"] },
  { id: "validation", label: "Validation", groups: ["validation", "close"] },
  { id: "setup", label: "Setup", groups: ["setup-salary", "setup-rules", "config"] },
  { id: "reports", label: "Reports", groups: ["reports"] },
  { id: "studio", label: "Studio", groups: ["studio"] },
];

export type TopMenu = { id: string; label: string; sections: NavGroup[] };

/** The menus for the groups this person can see; one with nothing in it is left out. */
export function topMenus(groups: NavGroup[]): TopMenu[] {
  return MENU_DEFS
    .map((m) => ({
      id: m.id,
      label: m.label,
      sections: m.groups.map((id) => groups.find((g) => g.id === id)).filter((g): g is NavGroup => !!g),
    }))
    .filter((m) => m.sections.length > 0);
}

export const ADMIN_ITEMS: NavItem[] = [
  { href: "/admin/users", label: "Users & roles", icon: Shield },
];

/** Pages reached from another page: pattern → [parent menu href, crumb label]. */
export const DETAIL_ROUTES: [RegExp, string, string][] = [
  [/^\/payroll\/results\/why/, "/payroll/results", "Why this result?"],
  [/^\/payroll\/runs\/compare/, "/payroll/results", "Compare runs"],
  [/^\/payroll\/employee\//, "/payroll/results", "Employee"],
  [/^\/studio\/connections\/oauth/, "/studio/connections", "Authorise"],
  [/^\/studio\/connections\/[^/]+/, "/studio/connections", "Connection"],
  [/^\/studio\/mapping\/[^/]+/, "/studio/mapping", "Mapping"],
  [/^\/studio\/workflows\/[^/]+/, "/studio/workflows", "Workflow"],
  [/^\/studio\/releases\/[^/]+/, "/studio/releases", "Release"],
  [/^\/studio\/runs\/[^/]+/, "/studio/runs", "Run"],
];

/** Menu items that are only active on their own page, not on pages beneath them. */
const EXACT = new Set(["/studio", "/reconciliation", "/reports"]);

export function isActiveHref(pathname: string, href: string): boolean {
  if (EXACT.has(href)) {
    if (pathname === href) return true;
    return DETAIL_ROUTES.some(([re, parent]) => parent === href && re.test(pathname));
  }
  if (pathname === href || pathname.startsWith(`${href}/`)) return true;
  return DETAIL_ROUTES.some(([re, parent]) => parent === href && re.test(pathname));
}

export type Crumb = { label: string; href?: string };

export function breadcrumbsFor(pathname: string, groups: NavGroup[]): Crumb[] {
  for (const g of groups) {
    const item = g.items.find((i) => isActiveHref(pathname, i.href));
    if (!item) continue;
    const crumbs: Crumb[] = [{ label: g.label, href: g.items[0].href }, { label: item.label, href: item.href }];
    const detail = DETAIL_ROUTES.find(([re]) => re.test(pathname));
    if (detail && pathname !== item.href) crumbs.push({ label: detail[2] });
    // A group whose first page is this page needs no separate group link.
    if (crumbs[0].href === item.href) crumbs[0] = { label: g.label };
    return crumbs;
  }
  return [{ label: "Workspace" }];
}

/**
 * Where to go after switching company. Anything in the URL that names a
 * record (a run, an employee, a release, a dashboard) belongs to the company
 * just left, so the page falls back to its section's list view.
 */
export function entityNeutralPath(pathname: string): string {
  const detail = DETAIL_ROUTES.find(([re]) => re.test(pathname));
  return detail ? detail[1] : pathname;
}
