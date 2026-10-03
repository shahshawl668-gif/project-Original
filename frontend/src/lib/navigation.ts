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
  BarChart3,
  BookOpen,
  Building2,
  Banknote,
  CalendarDays,
  Cable,
  ClipboardCheck,
  Code2,
  FileBarChart,
  FileCheck2,
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
  LayoutGrid,
  ListTodo,
  Loader,
  PlugZap,
  Scale,
  ScrollText,
  Settings2,
  Shield,
  Shuffle,
  Target,
  UploadCloud,
  UserPlus,
  Webhook,
  Workflow,
} from "lucide-react";

export type NavItem = { href: string; label: string; icon: LucideIcon };
export type NavGroup = {
  id: string;
  label: string;
  items: NavItem[];
  /** Large groups collapse unless you are inside them. */
  collapsible?: boolean;
};

export const NAV_GROUPS: NavGroup[] = [
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
      { href: "/ctc/upload", label: "CTC upload", icon: FileSpreadsheet },
      { href: "/ctc/history", label: "CTC history", icon: FolderArchive },
      { href: "/budget/upload", label: "Budget", icon: Target },
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
    label: "Reconciliation & approvals",
    items: [
      { href: "/reconciliation", label: "Month close & approval", icon: Scale },
      { href: "/reconciliation/disbursement", label: "Payment file check", icon: FileCheck2 },
      { href: "/reconciliation/bank", label: "Bank payments", icon: Banknote },
      { href: "/reconciliation/jv", label: "Journal voucher", icon: BookOpen },
    ],
  },
  {
    id: "analytics",
    label: "Analytics & dashboards",
    items: [
      { href: "/dashboards", label: "Dashboards", icon: LayoutGrid },
      { href: "/cost", label: "Cost analysis", icon: IndianRupee },
    ],
  },
  {
    id: "reports",
    label: "Reports",
    items: [
      { href: "/reports", label: "Report Centre", icon: FileDown },
      { href: "/reports/builder", label: "Report Builder", icon: FileBarChart },
    ],
  },
  {
    id: "studio",
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
    id: "config",
    label: "Configuration & admin",
    collapsible: true,
    items: [
      { href: "/config/companies", label: "Group companies", icon: Building2 },
      { href: "/config/statutory", label: "Statutory engine", icon: Settings2 },
      { href: "/config/tax", label: "Income tax & thresholds", icon: Landmark },
      { href: "/config/components", label: "Salary components", icon: Layers },
      { href: "/config/validation-matrix", label: "Validation matrix", icon: ClipboardCheck },
      { href: "/config/rules", label: "Rule suppressions", icon: Ban },
      { href: "/rule-engine/formula", label: "Formulas", icon: Code2 },
      { href: "/rule-engine/slabs", label: "PT / LWF slabs", icon: BarChart3 },
      { href: "/config/minimum-wage", label: "Minimum wage", icon: IndianRupee },
      { href: "/config/bank-profiles", label: "Bank file profiles", icon: Banknote },
      { href: "/config/jv-templates", label: "JV templates", icon: BookOpen },
      { href: "/config/upload", label: "Configuration upload", icon: FileSpreadsheet },
      { href: "/config/team", label: "Team & invitations", icon: UserPlus },
      { href: "/audit", label: "Audit trail", icon: ScrollText },
    ],
  },
];

export const ADMIN_ITEMS: NavItem[] = [
  { href: "/admin/users", label: "Users & roles", icon: Shield },
  { href: "/admin/support", label: "Support access", icon: KeyRound },
];

/** Pages reached from another page: pattern → [parent menu href, crumb label]. */
export const DETAIL_ROUTES: [RegExp, string, string][] = [
  [/^\/payroll\/results\/why/, "/payroll/results", "Why this result?"],
  [/^\/payroll\/runs\/compare/, "/payroll/results", "Compare runs"],
  [/^\/payroll\/employee\//, "/payroll/results", "Employee"],
  [/^\/dashboards\/[^/]+/, "/dashboards", "Dashboard"],
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
