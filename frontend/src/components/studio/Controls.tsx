"use client";

import { useEffect, useId, useState } from "react";
import { toast } from "sonner";
import { Check, Copy, Eye, EyeOff, FlaskConical, TriangleAlert } from "lucide-react";

import { Button, type ButtonProps } from "@/components/ui/button";
import { Dialog } from "@/components/ui/drawer";
import { cn } from "@/lib/utils";

/**
 * Studio's shared controls, so the same kind of action looks the same on
 * every page:
 *
 * - a test (send a test event, test a connection, try a formula) is an
 *   outline button with a flask — it changes nothing that matters;
 * - a dangerous action (revoke, disable, promote, cancel, reset) is a red
 *   outline button and always goes through `ConfirmAction`, which says what
 *   will happen before it happens;
 * - a secret shown once is masked until asked for, and copyable either way.
 */

export async function copyText(text: string, what = "Copied") {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(what);
    return true;
  } catch {
    toast.error("Could not copy — select the text and copy it by hand");
    return false;
  }
}

export function CopyButton({ value, label = "Copy", what, className, dark }: { value: string; label?: string; what?: string; className?: string; dark?: boolean }) {
  const [done, setDone] = useState(false);
  useEffect(() => { if (!done) return; const t = setTimeout(() => setDone(false), 1600); return () => clearTimeout(t); }, [done]);
  return (
    <button
      type="button"
      onClick={() => void copyText(value, what).then((ok) => setDone(ok))}
      aria-label={what ? `${label}: ${what.replace(/ copied$/i, "")}` : label}
      className={cn(
        "inline-flex h-7 flex-shrink-0 items-center gap-1 rounded-md px-2 text-[11px] font-medium transition-colors duration-fast",
        dark ? "bg-white/10 text-white hover:bg-white/20" : "border border-ink-200 bg-white text-ink-700 hover:bg-ink-50",
        className,
      )}
    >
      {done ? <Check size={11} aria-hidden /> : <Copy size={11} aria-hidden />} {done ? "Copied" : label}
    </button>
  );
}

/** A secret the server returns once. Masked on screen until revealed; Copy copies the whole value either way. */
export function SecretOnce({ title, value, children, onClose, testId = "shown-once" }: {
  title: string; value: string; children?: React.ReactNode; onClose: () => void; testId?: string;
}) {
  const [shown, setShown] = useState(false);
  const masked = `${value.slice(0, Math.min(8, Math.floor(value.length / 4)))}${"•".repeat(Math.max(8, Math.min(32, value.length - 8)))}`;
  return (
    <div role="alert" className="space-y-2.5 rounded-xl border border-warning-300 bg-warning-50 p-4 text-[13px] text-warning-950">
      <p className="flex items-center gap-2 font-semibold"><TriangleAlert size={16} aria-hidden /> {title} — copy it now; it will not be shown again</p>
      {children ? <div className="text-xs">{children}</div> : null}
      <div className="flex flex-wrap items-center gap-2">
        <code data-testid={testId} data-value={value} className="min-w-0 flex-1 break-all rounded-md border border-warning-200 bg-white px-2.5 py-1.5 font-mono text-xs text-ink-900">
          {shown ? value : masked}
        </code>
        <button type="button" onClick={() => setShown((s) => !s)} aria-pressed={shown}
          className="inline-flex h-7 items-center gap-1 rounded-md border border-warning-300 bg-white px-2 text-[11px] font-medium text-ink-800 hover:bg-warning-100">
          {shown ? <EyeOff size={11} aria-hidden /> : <Eye size={11} aria-hidden />} {shown ? "Hide" : "Reveal"}
        </button>
        <CopyButton value={value} what={`${title} copied`} />
      </div>
      <Button size="sm" variant="outline" onClick={onClose}>I have stored it</Button>
    </div>
  );
}

/** A test: harmless, visibly so. */
export function TestButton({ children, ...props }: ButtonProps) {
  return <Button variant="outline" size="sm" {...props}><FlaskConical size={13} aria-hidden /> {children}</Button>;
}

type Field =
  | { kind: "reason"; label: string; required?: boolean; placeholder?: string }
  | { kind: "hours"; label: string; min: number; max: number; initial: number; help?: string };

/**
 * Confirmation for an action that stops, removes or publishes something.
 * States the consequence, collects what the API needs (a reason, an overlap),
 * and names the action on its button — never a bare "OK".
 */
export function ConfirmAction({ open, onClose, title, consequence, confirmLabel, tone = "danger", field, onConfirm }: {
  open: boolean; onClose: () => void; title: string; consequence: React.ReactNode; confirmLabel: string;
  tone?: "danger" | "primary"; field?: Field; onConfirm: (value: string) => Promise<unknown> | void;
}) {
  const id = useId();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const initial = field?.kind === "hours" ? String(field.initial) : "";
  // Reset only when the dialog opens: `field` is a fresh object on every parent render.
  useEffect(() => { if (open) setValue(initial); }, [open, initial]);
  const hours = Number(value);
  const invalid = field?.kind === "reason" ? !!field.required && !value.trim()
    : field?.kind === "hours" ? !(value !== "" && Number.isInteger(hours) && hours >= field.min && hours <= field.max) : false;
  const go = async () => {
    setBusy(true);
    try { await onConfirm(value.trim()); onClose(); } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onClose={onClose} title={title}
      footer={<>
        <Button variant="outline" onClick={onClose} disabled={busy}>Keep as is</Button>
        <Button variant={tone === "danger" ? "destructive" : "default"} disabled={busy || invalid} onClick={() => void go()}>{confirmLabel}</Button>
      </>}>
      <div className="space-y-3 text-[13px] text-ink-700">
        <div>{consequence}</div>
        {field?.kind === "reason" ? (
          <label htmlFor={id} className="block text-xs font-medium text-ink-700">{field.label}{field.required ? "" : " (optional)"}
            <textarea id={id} className="mt-1 block min-h-[64px] w-full rounded-lg border border-ink-200 px-2.5 py-2 text-[13px]" placeholder={field.placeholder} value={value} onChange={(e) => setValue(e.target.value)} />
          </label>
        ) : field?.kind === "hours" ? (
          <label htmlFor={id} className="block text-xs font-medium text-ink-700">{field.label}
            <input id={id} type="number" min={field.min} max={field.max} step={1} className="mt-1 block h-9 w-32 rounded-lg border border-ink-200 px-2.5 text-[13px] tabular-nums" value={value} onChange={(e) => setValue(e.target.value)} aria-invalid={invalid} />
            <span className="mt-1 block font-normal text-ink-500">{field.help ?? `Whole hours, ${field.min}–${field.max}.`}</span>
          </label>
        ) : null}
      </div>
    </Dialog>
  );
}
