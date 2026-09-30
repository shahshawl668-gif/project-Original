"use client";

import { useState, type ReactNode } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/drawer";
import type { Change } from "@/lib/unsaved";
import { plural } from "@/lib/format";

const show = (v: unknown) =>
  v === null || v === undefined || v === "" ? "—" : Array.isArray(v) ? (v.length ? v.join(", ") : "none") : typeof v === "object" ? JSON.stringify(v) : String(v);

/**
 * Appears at the foot of the screen while there are unsaved changes: how
 * many, a review of each field before and after, Discard and Save. Saving
 * waits for the server; the bar only goes away once it has confirmed.
 */
export function SaveBar({
  changes,
  saving,
  onSave,
  onDiscard,
  label,
  note,
  canSave = true,
}: {
  changes: Change[];
  saving: boolean;
  onSave: () => void;
  onDiscard: () => void;
  label?: (field: string) => string;
  note?: ReactNode;
  canSave?: boolean;
}) {
  const [review, setReview] = useState(false);
  if (!changes.length) return null;
  const name = label ?? ((f: string) => f.replace(/_/g, " ").replace(/\./g, " › "));
  return (
    <>
      <div className="sticky bottom-0 z-30 -mx-4 mt-6 border-t border-ink-200 bg-white/95 px-4 py-3 shadow-[0_-4px_16px_-8px_rgb(16_24_40/0.12)] backdrop-blur sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8" role="region" aria-label="Unsaved changes">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-3">
          <p className="text-[13px] text-ink-800" aria-live="polite">
            <span className="mr-1.5 inline-block h-2 w-2 rounded-full bg-warning-500 align-middle" aria-hidden />
            <b>{plural(changes.length, "unsaved change")}</b>
            {note ? <span className="text-ink-500"> · {note}</span> : null}
          </p>
          <button type="button" className="text-xs font-medium text-brand-700 hover:underline" onClick={() => setReview(true)}>
            Review changes
          </button>
          <div className="ml-auto flex gap-2">
            <Button variant="ghost" onClick={onDiscard} disabled={saving}>Discard</Button>
            <Button onClick={onSave} disabled={saving || !canSave}>
              {saving ? <Loader2 size={14} className="animate-spin" /> : null}
              {saving ? "Saving…" : "Save changes"}
            </Button>
          </div>
        </div>
      </div>
      <Dialog
        open={review}
        onClose={() => setReview(false)}
        title="Review changes"
        description="Each field as it is saved now, and as it will be saved."
        className="sm:max-w-2xl"
        footer={
          <>
            <Button variant="outline" onClick={() => setReview(false)}>Keep editing</Button>
            <Button onClick={() => { setReview(false); onSave(); }} disabled={saving || !canSave}>Save changes</Button>
          </>
        }
      >
        <div className="scrollbar-thin max-h-[50vh] overflow-auto rounded-lg border border-ink-200">
          <table className="w-full border-separate border-spacing-0 text-[13px]">
            <thead>
              <tr className="[&>th]:sticky [&>th]:top-0 [&>th]:border-b [&>th]:border-ink-200 [&>th]:bg-ink-50 [&>th]:px-3 [&>th]:py-2 [&>th]:text-left [&>th]:text-xs [&>th]:font-medium [&>th]:text-ink-500">
                <th scope="col">Field</th><th scope="col">Saved now</th><th scope="col">Will be</th>
              </tr>
            </thead>
            <tbody>
              {changes.map((c) => (
                <tr key={c.field} className="[&>td]:border-b [&>td]:border-ink-100 [&>td]:px-3 [&>td]:py-1.5">
                  <td className="text-ink-700">{name(c.field)}</td>
                  <td className="num text-ink-500 line-through decoration-ink-300">{show(c.before)}</td>
                  <td className="num font-medium text-ink-900">{show(c.after)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Dialog>
    </>
  );
}
