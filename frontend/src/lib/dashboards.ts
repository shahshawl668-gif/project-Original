/**
 * Configurable dashboards: the client for /api/dashboards and /api/kpis.
 *
 * A tile is a stored question — dataset, metric or custom KPI, breakdown,
 * chart, filters, period — asked afresh each time the dashboard is opened.
 */
import { apiJson } from "@/lib/api";
import type { DataBasis } from "@/lib/cost-analysis";

export type Unit = "inr" | "number" | "pct";
export type Chart = "kpi" | "bar" | "line" | "pie" | "table";

export type DatasetMeta = {
  key: string; label: string; source: string;
  metrics: { key: string; label: string; unit: Unit; definition: string }[];
  breakdowns: { key: string; label: string }[];
  filters: string[];
};

export type Kpi = {
  id: string; name: string; description: string | null; dataset: string; formula: string; unit: Unit;
  visibility: "private" | "shared"; owner_user_id: string | null; mine: boolean; can_edit: boolean;
};

export type Catalogue = {
  datasets: DatasetMeta[];
  kpis: Kpi[];
  charts: Chart[];
  templates: { key: string; name: string; description: string; tiles: number }[];
};

export type PeriodSpec = { preset?: "last_3" | "last_6" | "last_12" | "all" | "custom" | null; inherit?: boolean; from?: string | null; to?: string | null };

export type Tile = {
  id?: string; title: string; dataset: string; metric?: string | null; kpi_id?: string | null;
  breakdown: string; chart: Chart; granularity: "month" | "quarter" | "year";
  filters: Record<string, string[]>; period: PeriodSpec;
};

export type Dashboard = {
  id: string; name: string; description: string | null; visibility: "private" | "shared";
  layout: { period: PeriodSpec; tiles: Tile[] }; template_key: string | null;
  owner_user_id: string | null; owner_email?: string | null; mine: boolean; can_edit: boolean; updated_at: string | null;
};

export type QueryResult = {
  dataset: { key: string; label: string; source: string };
  metric: { key: string; label: string; unit: Unit; definition: string; custom: boolean; formula?: string };
  breakdown: { key: string; label: string };
  period: { from: string | null; to: string | null; label: string };
  status: "ok" | "empty" | "no_data" | "no_budget";
  rows: { key: string; label: string; value: number | null; drill: string | null }[];
  total: number | null;
  note: string | null;
  basis: DataBasis | null;
};

const send = <T,>(path: string, method: string, body?: unknown) =>
  apiJson<T>(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });

export const dashboardsApi = {
  catalogue: () => apiJson<Catalogue>("/api/dashboards/datasets"),
  list: () => apiJson<Dashboard[]>("/api/dashboards"),
  get: (id: string) => apiJson<Dashboard>(`/api/dashboards/${encodeURIComponent(id)}`),
  create: (body: { name: string; description?: string | null; visibility: string; period: PeriodSpec; tiles: Tile[] }) =>
    send<Dashboard>("/api/dashboards", "POST", body),
  fromTemplate: (template: string) => send<Dashboard>("/api/dashboards/from-template", "POST", { template }),
  update: (id: string, body: { name: string; description?: string | null; visibility: string; period: PeriodSpec; tiles: Tile[] }) =>
    send<Dashboard>(`/api/dashboards/${encodeURIComponent(id)}`, "PUT", body),
  duplicate: (id: string) => send<Dashboard>(`/api/dashboards/${encodeURIComponent(id)}/duplicate`, "POST"),
  remove: (id: string) => send<{ deleted: boolean }>(`/api/dashboards/${encodeURIComponent(id)}`, "DELETE"),
  query: (tile: Tile, period: PeriodSpec) =>
    send<QueryResult>("/api/dashboards/query", "POST", {
      dataset: tile.dataset, metric: tile.kpi_id ? null : tile.metric, kpi_id: tile.kpi_id || null,
      breakdown: tile.breakdown, granularity: tile.granularity, filters: tile.filters,
      period: tile.period?.inherit || !tile.period?.preset ? period : tile.period,
    }),
  createKpi: (body: { name: string; description?: string | null; dataset: string; formula: string; unit: Unit; visibility: string }) =>
    send<Kpi>("/api/kpis", "POST", body),
  updateKpi: (id: string, body: { name: string; description?: string | null; dataset: string; formula: string; unit: Unit; visibility: string }) =>
    send<Kpi>(`/api/kpis/${encodeURIComponent(id)}`, "PUT", body),
  deleteKpi: (id: string) => send<{ deleted: boolean }>(`/api/kpis/${encodeURIComponent(id)}`, "DELETE"),
};

export function formatValue(value: number | null | undefined, unit: Unit): string {
  if (value === null || value === undefined) return "—";
  if (unit === "pct") return `${value.toLocaleString("en-IN", { maximumFractionDigits: 1 })}%`;
  if (unit === "inr") {
    const abs = Math.abs(value);
    if (abs >= 1e7) return `₹${(value / 1e7).toLocaleString("en-IN", { maximumFractionDigits: 2 })} Cr`;
    if (abs >= 1e5) return `₹${(value / 1e5).toLocaleString("en-IN", { maximumFractionDigits: 2 })} L`;
    return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
  }
  return value.toLocaleString("en-IN", { maximumFractionDigits: 1 });
}

export const PERIOD_PRESETS: { key: NonNullable<PeriodSpec["preset"]>; label: string }[] = [
  { key: "last_3", label: "Last 3 months" },
  { key: "last_6", label: "Last 6 months" },
  { key: "last_12", label: "Last 12 months" },
  { key: "all", label: "All months" },
  { key: "custom", label: "Custom range" },
];
