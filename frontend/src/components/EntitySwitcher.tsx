"use client";

import { useEffect, useRef, useState } from "react";
import { Building2, Check, ChevronDown } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { useEntity } from "@/context/EntityContext";
import { cn } from "@/lib/utils";

/**
 * Picks which employer the workspace is acting on.
 *
 * Hidden entirely for a single-entity organization: an enterprise with one
 * legal employer should never see a control that implies otherwise. It appears
 * as soon as there is a real choice to make.
 */
export function EntitySwitcher() {
  const { entity, entities, isMultiEntity, organization, switchEntity, loading } = useEntity();
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (loading || !entity || !isMultiEntity) return null;

  async function onSelect(entityId: string) {
    if (entityId === entity?.id) {
      setOpen(false);
      return;
    }
    setSwitching(entityId);
    try {
      await switchEntity(entityId);
      // Everything cached belongs to the entity we just left.
      await queryClient.invalidateQueries();
    } finally {
      setSwitching(null);
      setOpen(false);
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="inline-flex max-w-[15rem] items-center gap-2 rounded-xl border border-ink-200/70 bg-white px-3 py-1.5 text-xs font-semibold text-ink-800 shadow-sm transition-colors hover:border-brand-300 hover:bg-ink-50 dark:border-white/10 dark:bg-white/[0.04] dark:text-ink-100 dark:hover:border-brand-500/40 dark:hover:bg-white/[0.08]"
      >
        <Building2 size={14} className="flex-shrink-0 text-brand-600 dark:text-brand-400" />
        <span className="truncate">{entity.name}</span>
        <ChevronDown size={13} className="flex-shrink-0 text-ink-400" aria-hidden />
      </button>

      {open && (
        <div
          role="listbox"
          className="absolute right-0 z-50 mt-2 max-h-80 w-72 overflow-y-auto rounded-xl border border-ink-200/70 bg-white p-1.5 shadow-lg dark:border-white/10 dark:bg-ink-900"
        >
          {organization && (
            <p className="px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-wide text-ink-400">
              {organization.org_type === "practice" ? "Clients" : "Entities"} · {organization.name}
            </p>
          )}
          {entities.map((candidate) => {
            const active = candidate.id === entity.id;
            return (
              <button
                key={candidate.id}
                type="button"
                role="option"
                aria-selected={active}
                disabled={switching !== null}
                onClick={() => void onSelect(candidate.id)}
                className={cn(
                  "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs transition-colors disabled:opacity-60",
                  active
                    ? "bg-brand-50 text-brand-800 dark:bg-brand-500/10 dark:text-brand-200"
                    : "text-ink-700 hover:bg-ink-50 dark:text-ink-200 dark:hover:bg-white/[0.06]",
                )}
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-semibold">{candidate.name}</span>
                  <span className="block truncate text-[10px] text-ink-400">
                    {candidate.code}
                    {candidate.primary_state ? ` · ${candidate.primary_state}` : ""}
                  </span>
                </span>
                {active && <Check size={14} className="flex-shrink-0" aria-hidden />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
