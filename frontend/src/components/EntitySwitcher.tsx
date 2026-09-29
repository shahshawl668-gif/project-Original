"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Building2, Check, ChevronDown, Loader2 } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { entityNeutralPath } from "@/lib/navigation";
import { cn } from "@/lib/utils";

/**
 * Which company the workspace is acting on — always visible, because every
 * number on every page belongs to one company.
 *
 * With one company it is a plain label. With several it switches, and a
 * switch is a clean break: the query cache is emptied and the page remounts
 * (EntityContext), and a URL naming a record of the old company falls back to
 * its list.
 */
export function EntitySwitcher() {
  const { entity, entities, isMultiEntity, organization, switchEntity, loading } = useEntity();
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) setOpen(false);
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

  if (loading && !entity) return <span className="h-8 w-40 animate-pulse-soft rounded-lg bg-ink-100" aria-hidden />;
  if (!entity) return null;

  if (!isMultiEntity) {
    return (
      <span
        className="inline-flex max-w-[15rem] items-center gap-1.5 rounded-lg px-2 py-1 text-[13px] font-medium text-ink-800"
        title={entity.legal_name ?? entity.name}
      >
        <Building2 size={14} className="flex-shrink-0 text-ink-400" aria-hidden />
        <span className="truncate">{entity.name}</span>
      </span>
    );
  }

  async function onSelect(entityId: string) {
    if (entityId === entity?.id) {
      setOpen(false);
      return;
    }
    setSwitching(entityId);
    try {
      // Clears the query cache and remounts the page (see EntityContext).
      await switchEntity(entityId);
      const neutral = entityNeutralPath(pathname);
      if (neutral !== pathname || window.location.search) router.replace(neutral);
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
        aria-label={`Company: ${entity.name}. Switch company`}
        className="inline-flex h-8 max-w-[15rem] items-center gap-1.5 rounded-lg border border-ink-200 bg-white px-2.5 text-[13px] font-medium text-ink-800 shadow-soft transition-colors hover:border-ink-300 hover:bg-ink-50"
      >
        {switching ? (
          <Loader2 size={14} className="flex-shrink-0 animate-spin text-brand-600" aria-hidden />
        ) : (
          <Building2 size={14} className="flex-shrink-0 text-ink-400" aria-hidden />
        )}
        <span className="truncate">{entity.name}</span>
        <ChevronDown size={13} className="flex-shrink-0 text-ink-400" aria-hidden />
      </button>

      {open && (
        <div
          role="listbox"
          aria-label="Companies"
          className="absolute right-0 z-50 mt-1.5 max-h-80 w-72 animate-fade-up overflow-y-auto rounded-xl border border-ink-200 bg-white p-1 shadow-elevated"
        >
          {organization && (
            <p className="px-2.5 pb-1 pt-1.5 text-xs text-ink-500">
              {organization.org_type === "practice" ? "Clients" : "Companies"} in {organization.name}
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
                  "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] transition-colors disabled:opacity-60",
                  active ? "bg-brand-50 text-brand-900" : "text-ink-700 hover:bg-ink-50",
                )}
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{candidate.name}</span>
                  <span className="block truncate text-xs text-ink-500">
                    {candidate.code}
                    {candidate.primary_state ? ` · ${candidate.primary_state}` : ""}
                  </span>
                </span>
                {switching === candidate.id ? (
                  <Loader2 size={14} className="flex-shrink-0 animate-spin" aria-hidden />
                ) : active ? (
                  <Check size={14} className="flex-shrink-0 text-brand-700" aria-hidden />
                ) : null}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
