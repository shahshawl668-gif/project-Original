"use client";

import { useState } from "react";
import { Download } from "lucide-react";
import { toast } from "sonner";

import { apiBlob } from "@/lib/api";
import { saveBlob } from "@/lib/download";

/**
 * Template buttons: CSV and Excel, always, built on the server from this
 * company's own salary components so a component added today is a column today.
 */
export function TemplateDownload({ kind, label = "Template" }: { kind: "register" | "ctc" | "attendance" | "master"; label?: string }) {
  const [busy, setBusy] = useState(false);
  const get = async (ext: "csv" | "xlsx") => {
    setBusy(true);
    try {
      saveBlob(await apiBlob(`/api/templates/${kind}.${ext}`), `${kind}-template.${ext}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "The template could not be downloaded.");
    } finally {
      setBusy(false);
    }
  };
  const cls = "inline-flex h-9 items-center gap-1.5 border border-ink-200 px-3 text-sm font-medium text-ink-700 transition hover:bg-ink-50 disabled:opacity-60";
  return (
    <span className="inline-flex items-center" role="group" aria-label={`${label} download`}>
      <span className="mr-2 text-xs font-semibold text-ink-500">{label}</span>
      <button type="button" disabled={busy} onClick={() => void get("csv")} className={`${cls} rounded-l-lg`}>
        <Download size={14} /> CSV
      </button>
      <button type="button" disabled={busy} onClick={() => void get("xlsx")} className={`${cls} -ml-px rounded-r-lg`}>
        <Download size={14} /> Excel
      </button>
    </span>
  );
}
