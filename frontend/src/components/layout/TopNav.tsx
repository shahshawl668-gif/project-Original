"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { isActiveHref, topMenus, type NavGroup } from "@/lib/navigation";
import { cn } from "@/lib/utils";

/**
 * The top bar. Each heading opens a panel; a heading that holds several groups
 * shows them as a rail on the left with the pages of the chosen group beside it.
 * Opens on hover or click, closes on Escape, a click elsewhere or a page change.
 */
export function TopNav({ groups }: { groups: NavGroup[] }) {
  const pathname = usePathname();
  const menus = useMemo(() => topMenus(groups), [groups]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [sectionId, setSectionId] = useState<string | null>(null);
  const bar = useRef<HTMLElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => setOpenId(null), [pathname]);
  useEffect(() => {
    if (!openId) return;
    const down = (e: MouseEvent) => !bar.current?.contains(e.target as Node) && setOpenId(null);
    const key = (e: KeyboardEvent) => e.key === "Escape" && setOpenId(null);
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", down);
      document.removeEventListener("keydown", key);
    };
  }, [openId]);

  const open = (id: string) => {
    clearTimeout(timer.current);
    const menu = menus.find((m) => m.id === id);
    const current = menu?.sections.find((g) => g.items.some((i) => isActiveHref(pathname, i.href)));
    setSectionId(current?.id ?? menu?.sections[0]?.id ?? null);
    setOpenId(id);
  };
  const closeSoon = () => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setOpenId(null), 180);
  };

  return (
    <nav
      ref={bar}
      aria-label="Main"
      className="relative z-40 hidden bg-ink-900 text-white lg:block"
      onMouseLeave={closeSoon}
      onMouseEnter={() => clearTimeout(timer.current)}
    >
      <ul className="flex items-stretch gap-0.5 px-5">
        {menus.map((menu) => {
          const holdsPage = menu.sections.some((g) => g.items.some((i) => isActiveHref(pathname, i.href)));
          const isOpen = openId === menu.id;
          return (
            <li key={menu.id} className="relative" onMouseEnter={() => open(menu.id)}>
              <button
                type="button"
                aria-haspopup="true"
                aria-expanded={isOpen}
                onClick={() => (isOpen ? setOpenId(null) : open(menu.id))}
                className={cn(
                  "flex h-11 items-center gap-1 px-3.5 text-[13.5px] font-medium transition-colors",
                  isOpen ? "bg-white/15" : "hover:bg-white/10",
                  holdsPage ? "border-b-2 border-brand-500" : "border-b-2 border-transparent",
                )}
              >
                {menu.label}
                <ChevronDown size={13} aria-hidden className={cn("opacity-70 transition-transform", isOpen && "rotate-180")} />
              </button>

              {isOpen ? (
                <div
                  role="menu"
                  aria-label={menu.label}
                  className="absolute left-0 top-full flex min-w-[320px] animate-fade-up overflow-hidden rounded-b-xl border border-white/10 bg-ink-900 shadow-elevated"
                >
                  {menu.sections.length > 1 ? (
                    <ul className="w-48 flex-shrink-0 border-r border-white/10 py-2">
                      {menu.sections.map((g) => (
                        <li key={g.id}>
                          <button
                            type="button"
                            onMouseEnter={() => setSectionId(g.id)}
                            onClick={() => setSectionId(g.id)}
                            aria-current={sectionId === g.id}
                            className={cn(
                              "flex w-full items-center justify-between px-4 py-2.5 text-left text-[13px] transition-colors",
                              sectionId === g.id ? "bg-white/15 font-medium" : "text-ink-200 hover:bg-white/10",
                            )}
                          >
                            {g.label}
                            <ChevronDown size={13} aria-hidden className="-rotate-90 opacity-60" />
                          </button>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  <ul className={cn("grid gap-x-1 p-2", menu.sections.length > 1 ? "min-w-[420px] grid-cols-2" : "min-w-[400px] grid-cols-1 sm:grid-cols-2")}>
                    {(menu.sections.find((g) => g.id === sectionId) ?? menu.sections[0]).items.map((item) => {
                      const Icon = item.icon;
                      const active = isActiveHref(pathname, item.href);
                      return (
                        <li key={item.href}>
                          <Link
                            href={item.href}
                            role="menuitem"
                            aria-current={active ? "page" : undefined}
                            className={cn(
                              "flex items-center gap-2.5 rounded-md px-3 py-2.5 text-[13.5px] transition-colors",
                              active ? "bg-white/15 font-medium" : "text-ink-100 hover:bg-white/10",
                            )}
                          >
                            <Icon size={15} aria-hidden className="flex-shrink-0 opacity-70" />
                            <span className="truncate">{item.label}</span>
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
