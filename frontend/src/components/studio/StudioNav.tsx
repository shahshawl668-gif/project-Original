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
    <nav aria-label="Studio sections" className="scrollbar-thin -mx-1 overflow-x-auto border-b border-ink-200">
      <ul className="flex min-w-max gap-1 px-1">
        {list.map((s) => {
          const active = s.href === "/studio" ? pathname === "/studio" : !!s.href && pathname.startsWith(s.href);
          return (
            <li key={s.key}>
              {s.available && s.href ? (
                <Link href={s.href} aria-current={active ? "page" : undefined}
                  className={cn("-mb-px inline-flex h-10 items-center border-b-2 px-3 text-[13px] font-medium transition-colors duration-fast",
                    active ? "border-brand-600 text-ink-900" : "border-transparent text-ink-600 hover:border-ink-300 hover:text-ink-900")}>
                  {s.label}
                </Link>
              ) : (
                <span title={s.summary} aria-disabled="true"
                  className="-mb-px inline-flex h-10 cursor-not-allowed items-center border-b-2 border-transparent px-3 text-[13px] text-ink-500">
                  {s.label}<span className="ml-1 text-[11px]">· not in this release</span>
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
