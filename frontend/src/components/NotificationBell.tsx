"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { studioFlowApi } from "@/lib/studio";
import { cn } from "@/lib/utils";

const DOT = { info: "bg-brand-500", warning: "bg-warning-500", error: "bg-danger-500" } as const;

/**
 * In-product notifications for the company in view — sent by workflows. They
 * are the reader's own; a link opens a page that checks the reader's access.
 */
export function NotificationBell() {
  const { entity } = useEntity();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const q = useQuery({ queryKey: ["notifications", entity?.id], queryFn: studioFlowApi.notifications, enabled: !!entity,
    refetchInterval: 60_000, retry: false });
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  if (!q.data) return null;
  const read = async (ids?: string[]) => {
    await studioFlowApi.markRead(ids);
    await qc.invalidateQueries({ queryKey: ["notifications", entity?.id] });
  };
  const unread = q.data.unread;
  return (
    <div className="relative" ref={box}>
      <button type="button" aria-label={unread ? `${unread} unread notification(s)` : "Notifications"} onClick={() => setOpen(!open)}
        className="relative rounded-lg p-2 text-ink-500 hover:bg-ink-100 hover:text-ink-900">
        <Bell size={18} />
        {unread ? <span className="absolute -right-0.5 -top-0.5 min-w-[1.1rem] rounded-full bg-danger-600 px-1 text-center text-[10px] font-bold text-white">{unread > 9 ? "9+" : unread}</span> : null}
      </button>
      {open ? (
        <div className="absolute right-0 z-50 mt-2 w-96 max-w-[90vw] rounded-xl border border-ink-200 bg-white p-2 shadow-xl" role="dialog" aria-label="Notifications">
          <div className="flex items-center justify-between px-2 py-1">
            <span className="text-sm font-semibold">Notifications</span>
            {unread ? <button type="button" className="text-xs text-brand-700 underline" onClick={() => void read()}>Mark all read</button> : null}
          </div>
          {q.data.items.length === 0 ? <p className="px-2 py-4 text-sm text-ink-500">Nothing yet. Workflows send notifications here.</p> : (
            <ul className="max-h-96 divide-y divide-ink-100 overflow-y-auto">
              {q.data.items.map((n) => {
                const body = (
                  <>
                    <span className="flex items-center gap-2"><span className={cn("h-2 w-2 flex-shrink-0 rounded-full", n.read ? "bg-ink-200" : DOT[n.severity])} />
                      <span className={cn("text-sm", n.read ? "text-ink-500" : "font-semibold text-ink-900")}>{n.title}</span></span>
                    {n.body ? <span className="block pl-4 text-xs text-ink-500">{n.body}</span> : null}
                    <span className="block pl-4 text-[11px] text-ink-500">{n.created_at ? new Date(n.created_at).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : ""}</span>
                  </>
                );
                return (
                  <li key={n.id} className="px-2 py-2">
                    {n.link ? <Link href={n.link} onClick={() => { setOpen(false); if (!n.read) void read([n.id]); }} className="block hover:underline">{body}</Link>
                      : <button type="button" className="block w-full text-left" onClick={() => { if (!n.read) void read([n.id]); }}>{body}</button>}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
