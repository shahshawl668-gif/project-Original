/**
 * Formatting shared by every screen: rupees in the Indian grouping, counts,
 * dates, and — most important — a missing value that looks missing.
 *
 * `null`/`undefined` never format as 0. A figure that was not calculated says
 * "Not calculated"; one that has no source says "—". Zero is only ever shown
 * for a real zero.
 */

export const MISSING = "—";

export function inr(value: number | null | undefined, opts: { digits?: number; missing?: string } = {}): string {
  if (value === null || value === undefined || Number.isNaN(value)) return opts.missing ?? MISSING;
  const digits = opts.digits ?? 0;
  const sign = value < 0 ? "−" : "";
  return `${sign}₹${Math.abs(value).toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

/** ₹1.2 L, ₹3.4 Cr — for tiles and axes. Tables use `inr`. */
export function inrCompact(value: number | null | undefined, missing = MISSING): string {
  if (value === null || value === undefined || Number.isNaN(value)) return missing;
  const abs = Math.abs(value);
  const sign = value < 0 ? "−" : "";
  if (abs >= 1e7) return `${sign}₹${(abs / 1e7).toLocaleString("en-IN", { maximumFractionDigits: 2 })} Cr`;
  if (abs >= 1e5) return `${sign}₹${(abs / 1e5).toLocaleString("en-IN", { maximumFractionDigits: 2 })} L`;
  return inr(value);
}

export function count(value: number | null | undefined, missing = MISSING): string {
  if (value === null || value === undefined || Number.isNaN(value)) return missing;
  return value.toLocaleString("en-IN");
}

export function pct(value: number | null | undefined, digits = 0, missing = MISSING): string {
  if (value === null || value === undefined || Number.isNaN(value)) return missing;
  return `${value.toLocaleString("en-IN", { maximumFractionDigits: digits })}%`;
}

export function date(iso: string | null | undefined, missing = MISSING): string {
  if (!iso) return missing;
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export function dateTime(iso: string | null | undefined, missing = MISSING): string {
  if (!iso) return missing;
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** "3 minutes ago", falling back to the date after a week. */
export function ago(iso: string | null | undefined, missing = MISSING): string {
  if (!iso) return missing;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const s = Math.round((Date.now() - t) / 1000);
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  if (d < 7) return `${d} day${d > 1 ? "s" : ""} ago`;
  return date(iso);
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString("en-IN")} ${n === 1 ? one : many}`;
}
