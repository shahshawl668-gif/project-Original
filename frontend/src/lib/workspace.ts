"use client";

/**
 * The working period: which month the person is working on, shared by every
 * screen that is about one month.
 *
 * Stored per company in session storage, so switching company never carries
 * one company's month into another, and a new tab starts fresh. When nothing
 * has been chosen, the month of the latest validation run is used — the month
 * someone was last working on — and failing that, the current calendar month.
 * The header says which of those it is showing, so a default is never mistaken
 * for a choice.
 */
import { useCallback, useEffect, useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";

import { useEntity } from "@/context/EntityContext";
import { validationApi } from "@/lib/validation";

const EVENT = "pol:working-period";
const key = (entityId: string) => `pol_working_period:${entityId}`;

function read(entityId: string | undefined): string | null {
  if (!entityId || typeof window === "undefined") return null;
  try {
    return sessionStorage.getItem(key(entityId));
  } catch {
    return null;
  }
}

export function setWorkingPeriod(entityId: string, period: string) {
  const month = normalisePeriod(period);
  if (!month) return;
  try {
    sessionStorage.setItem(key(entityId), month);
  } catch {
    /* storage blocked: the choice lasts until the page reloads */
  }
  window.dispatchEvent(new Event(EVENT));
}

/** "2026-06", "2026-06-01" or an ISO timestamp → "2026-06". */
export function normalisePeriod(value: string | null | undefined): string | null {
  if (!value) return null;
  const m = /^(\d{4})-(\d{2})/.exec(value);
  return m ? `${m[1]}-${m[2]}` : null;
}

export function periodLabel(period: string | null | undefined): string {
  const month = normalisePeriod(period);
  if (!month) return "—";
  const [y, m] = month.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "short", year: "numeric" });
}

export function periodToDate(period: string): string {
  return `${normalisePeriod(period)}-01`;
}

function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function subscribe(cb: () => void) {
  window.addEventListener(EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(EVENT, cb);
    window.removeEventListener("storage", cb);
  };
}

export type PeriodSource = "chosen" | "latest-run" | "calendar";

export function useWorkingPeriod() {
  const { entity } = useEntity();
  const entityId = entity?.id;
  const chosen = useSyncExternalStore(
    subscribe,
    () => read(entityId),
    () => null,
  );
  const latest = useQuery({
    queryKey: ["latest-run", entityId],
    queryFn: () => validationApi.runs({ limit: 1 }),
    enabled: !!entityId && !chosen,
    staleTime: 5 * 60_000,
    retry: false,
  });
  const latestPeriod = normalisePeriod(latest.data?.[0]?.period_month);
  const period = chosen ?? latestPeriod ?? (latest.isLoading ? null : currentMonth());
  const source: PeriodSource = chosen ? "chosen" : latestPeriod ? "latest-run" : "calendar";
  const set = useCallback((p: string) => entityId && setWorkingPeriod(entityId, p), [entityId]);
  return { period, source, setPeriod: set, loading: !chosen && latest.isLoading };
}

/** Adopt a period that arrived in the URL (?period=) as the working period. */
export function useAdoptPeriod(period: string | null | undefined) {
  const { entity } = useEntity();
  useEffect(() => {
    if (entity?.id && period && normalisePeriod(period) !== read(entity.id)) setWorkingPeriod(entity.id, period);
  }, [entity?.id, period]);
}
