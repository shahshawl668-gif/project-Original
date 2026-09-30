"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import type { ReactNode } from "react";

const KEY = "pol_nav_depth";

/** Called by the shell on every in-app navigation. */
export function noteNavigation() {
  try {
    sessionStorage.setItem(KEY, String(Number(sessionStorage.getItem(KEY) || 0) + 1));
  } catch {
    /* without storage, Back falls back to the parent page */
  }
}

function cameFromInsideTheApp(): boolean {
  try {
    return Number(sessionStorage.getItem(KEY) || 0) > 1;
  } catch {
    return false;
  }
}

/**
 * Back to where the reader came from — the table with its filters, page and
 * scroll position — when they arrived from inside the product; otherwise to
 * the parent page, so a link opened from an email still has somewhere to go.
 */
export function BackLink({ fallback, children }: { fallback: string; children: ReactNode }) {
  const router = useRouter();
  return (
    <Link
      href={fallback}
      onClick={(e) => {
        if (cameFromInsideTheApp() && window.history.length > 1) {
          e.preventDefault();
          router.back();
        }
      }}
      className="inline-flex items-center gap-1 text-[13px] font-medium text-ink-600 transition-colors hover:text-ink-900"
    >
      <ArrowLeft size={14} aria-hidden />
      {children}
    </Link>
  );
}
