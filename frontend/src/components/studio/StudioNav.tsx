"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { useEntity } from "@/context/EntityContext";
import { studioApi, type Section } from "@/lib/studio";
import { cn } from "@/lib/utils";

const FALLBACK: Section[] = [
  { key: "overview", label: "Overview", href: "/studio", available: true, summary: "" },
];

/**
 * The Studio's section bar. Sections this release provides are links; the
 * rest are listed, greyed, and say "not in this release" — never a link to a
 * page that only looks like it works.
 */
export function StudioNav() {
  const pathname = usePathname();
  const { entity } = useEntity();
  const overview = useQuery({ queryKey: ["studio-overview", entity?.id], queryFn: studioApi.overview, enabled: !!entity });
  const sections = [
    { key: "overview", label: "Overview", href: "/studio", available: true, summary: "" },
    ...(overview.data?.sections ?? []),
  ];
  const list = overview.data ? sections : FALLBACK;
  return (
    <nav aria-label="Studio sections" className="-mx-1 flex flex-wrap gap-1 border-b border-ink-100 pb-2">
      {list.map((s) => {
        const active = s.href === "/studio" ? pathname === "/studio" : !!s.href && pathname.startsWith(s.href);
        return s.available && s.href ? (
          <Link key={s.key} href={s.href}
            className={cn("rounded-lg px-3 py-1.5 text-sm font-medium",
              active ? "bg-brand-600 text-white" : "text-ink-700 hover:bg-ink-100")}>
            {s.label}
          </Link>
        ) : (
          <span key={s.key} title={s.summary} aria-disabled="true"
            className="cursor-not-allowed rounded-lg px-3 py-1.5 text-sm text-ink-400">
            {s.label} <span className="text-[11px]">· not in this release</span>
          </span>
        );
      })}
    </nav>
  );
}
