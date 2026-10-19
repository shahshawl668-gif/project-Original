"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle2, ChevronDown, XCircle } from "lucide-react";

import {
  type FormulaRuleType,
  type FormulaVariables,
  getFormulaVariables,
  testFormula,
} from "@/lib/rule-engine";
import { cn } from "@/lib/utils";

/** How companies commonly write it. The numbers are examples; change them to your own policy. */
const EXAMPLES: Record<FormulaRuleType, { title: string; expression: string }[]> = {
  PF: [
    { title: "12% of PF wage, up to a ceiling", expression: "MIN(pf_wage, 25000) * 12%" },
    { title: "12% of Basic", expression: "basic * 12%" },
    { title: "12% of Basic, at most 3,000", expression: "MIN(basic * 12%, 3000)" },
    {
      title: "Lower paid: Basic + a component, capped. Others: Basic",
      expression: "IF(basic <= 25000, MIN((basic + special_allowance) * 12%, 3000), basic * 12%)",
    },
  ],
  ESIC: [
    { title: "0.75% of ESIC wage, rounded up", expression: "IF(esic_wage <= 21000, ROUNDUP(esic_wage * 0.75%, 0), 0)" },
    { title: "0.75% of gross, nearest rupee", expression: "IF(gross <= 21000, ROUND_HALF_UP(gross * 0.75%), 0)" },
    {
      title: "On chosen components",
      expression: "IF((basic + hra) <= 21000, ROUNDUP((basic + hra) * 0.75%, 0), 0)",
    },
  ],
};

const SAMPLE: Record<string, string> = {
  basic: "20000", da: "0", hra: "8000", gross: "40000", pf_wage: "28000", esic_wage: "20000",
  ctc_monthly: "40000", paid_days: "31", lop_days: "0", total_days: "31",
};

/**
 * The employee's PF or ESIC, either from the rates and ceiling (standard) or from
 * a formula written like in Excel. Leaving it standard stores nothing.
 */
export function EmployeeFormula({
  kind,
  value,
  onChange,
}: {
  kind: FormulaRuleType;
  value: string;
  onChange: (next: string) => void;
}) {
  const [custom, setCustom] = useState(!!value);
  const [variables, setVariables] = useState<FormulaVariables | null>(null);
  const [verdict, setVerdict] = useState<{ ok: boolean; message: string } | null>(null);
  const [sample, setSample] = useState<Record<string, string>>({});
  const [tried, setTried] = useState<string | null>(null);
  const remembered = useRef(value || EXAMPLES[kind][0].expression);
  const field = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    getFormulaVariables().then(setVariables).catch(() => setVariables(null));
  }, []);

  useEffect(() => {
    if (!value.trim()) {
      setVerdict(null);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const r = await testFormula({ expression: value, conditions: [], variables: {} });
        setVerdict(r.ok ? { ok: true, message: "The formula reads correctly." } : { ok: false, message: r.error ?? "Not valid" });
      } catch {
        setVerdict(null);
      }
    }, 400);
    return () => clearTimeout(t);
  }, [value]);

  const all = useMemo(() => [...(variables?.inputs ?? []), ...(variables?.components ?? [])], [variables]);
  const used = useMemo(() => {
    const text = value.toLowerCase().replace(/[^a-z0-9_]+/g, " ");
    const words = new Set(text.split(" "));
    return all.filter((v) => words.has(v.key));
  }, [value, all]);

  const choose = (nextCustom: boolean) => {
    if (nextCustom === custom) return;
    if (!nextCustom) remembered.current = value || remembered.current;
    setCustom(nextCustom);
    onChange(nextCustom ? remembered.current : "");
  };

  const insert = (text: string) => {
    const el = field.current;
    const at = el?.selectionStart ?? value.length;
    const end = el?.selectionEnd ?? value.length;
    onChange(value.slice(0, at) + text + value.slice(end));
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(at + text.length, at + text.length);
    });
  };

  const tryIt = async () => {
    const numbers: Record<string, number> = {};
    for (const v of used) numbers[v.key] = Number(sample[v.key] ?? SAMPLE[v.key] ?? "5000") || 0;
    try {
      const r = await testFormula({ expression: value, conditions: [], variables: numbers });
      setTried(r.ok ? `= ${(r.result ?? 0).toLocaleString("en-IN", { maximumFractionDigits: 2 })}` : (r.error ?? "Could not be worked out"));
    } catch (e) {
      setTried((e as Error).message);
    }
  };

  return (
    <div className="rounded-xl border border-ink-200 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold text-ink-500">How is the employee&apos;s {kind} worked out?</p>
        <div role="radiogroup" aria-label={`${kind} calculation`} className="inline-flex rounded-lg border border-ink-200 p-0.5 text-[13px]">
          {[
            { id: false, label: "Rate × wage" },
            { id: true, label: "My own formula" },
          ].map((o) => (
            <button
              key={String(o.id)}
              type="button"
              role="radio"
              aria-checked={custom === o.id}
              onClick={() => choose(o.id)}
              className={cn(
                "rounded-md px-3 py-1 font-medium transition",
                custom === o.id ? "bg-brand-600 text-white" : "text-ink-700 hover:bg-ink-50",
              )}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      {!custom ? (
        <p className="mt-2 text-xs text-ink-500">
          Uses the rate, wage and ceiling below. Choose “My own formula” when your company calculates it differently.
        </p>
      ) : (
        <div className="mt-3 space-y-2.5">
          <textarea
            ref={field}
            value={value}
            rows={2}
            spellCheck={false}
            onChange={(e) => onChange(e.target.value)}
            aria-label={`${kind} formula`}
            placeholder="e.g. MIN((basic + special_allowance) * 12%, 3000)"
            className={cn(
              "w-full rounded-lg border bg-white p-2.5 font-mono text-[13px] text-ink-900 focus:outline-none focus:ring-2 focus:ring-brand-500/20",
              verdict && !verdict.ok ? "border-danger-500" : "border-ink-200",
            )}
          />
          {verdict ? (
            <p className={cn("flex items-start gap-1.5 text-xs", verdict.ok ? "text-success-700" : "text-danger-700")}>
              {verdict.ok ? <CheckCircle2 size={14} className="mt-px shrink-0" /> : <XCircle size={14} className="mt-px shrink-0" />}
              {verdict.message}
            </p>
          ) : null}
          <p className="text-xs text-ink-500">
            Write it like in Excel: <span className="font-mono">12%</span> is 12 percent; <span className="font-mono">IF AND OR MIN MAX ROUNDUP ROUNDDOWN</span>; capitals do not matter.
            The result is the employee&apos;s {kind} for the month, and the payslip is compared with it.
          </p>

          <details className="group text-xs">
            <summary className="flex cursor-pointer list-none items-center gap-1 font-medium text-ink-700">
              <ChevronDown size={13} className="transition group-open:rotate-180" /> Insert a field
            </summary>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {all.map((v) => (
                <button
                  key={v.key}
                  type="button"
                  title={v.label}
                  onClick={() => insert(v.key)}
                  className="rounded-full border border-ink-200 px-2 py-0.5 font-mono text-[11px] text-ink-700 hover:bg-brand-50"
                >
                  {v.key}
                </button>
              ))}
              {variables && variables.components.length === 0 ? (
                <span className="text-ink-500">Your salary components appear here once they are added.</span>
              ) : null}
            </div>
          </details>

          <details className="group text-xs">
            <summary className="flex cursor-pointer list-none items-center gap-1 font-medium text-ink-700">
              <ChevronDown size={13} className="transition group-open:rotate-180" /> Examples
            </summary>
            <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
              {EXAMPLES[kind].map((e) => (
                <button
                  key={e.expression}
                  type="button"
                  onClick={() => onChange(e.expression)}
                  className="rounded-lg border border-ink-200 p-2 text-left hover:border-brand-300 hover:bg-brand-50/50"
                >
                  <span className="block font-medium text-ink-900">{e.title}</span>
                  <code className="mt-0.5 block break-words text-[11px] text-ink-600">{e.expression}</code>
                </button>
              ))}
            </div>
          </details>

          <details className="group text-xs">
            <summary className="flex cursor-pointer list-none items-center gap-1 font-medium text-ink-700">
              <ChevronDown size={13} className="transition group-open:rotate-180" /> Try it with sample figures
            </summary>
            <div className="mt-2 flex flex-wrap items-end gap-2">
              {used.length === 0 ? <span className="text-ink-500">Fields you use in the formula appear here.</span> : null}
              {used.map((v) => (
                <label key={v.key} className="block">
                  <span className="mb-0.5 block font-mono text-[11px] text-ink-500">{v.key}</span>
                  <input
                    type="number"
                    value={sample[v.key] ?? SAMPLE[v.key] ?? "5000"}
                    onChange={(e) => setSample((s) => ({ ...s, [v.key]: e.target.value }))}
                    className="h-8 w-24 rounded-md border border-ink-200 px-2 text-[13px]"
                  />
                </label>
              ))}
              <button
                type="button"
                onClick={() => void tryIt()}
                disabled={!value.trim() || (verdict ? !verdict.ok : false)}
                className="h-8 rounded-md border border-ink-200 px-3 text-[13px] font-medium text-ink-800 hover:bg-ink-50 disabled:opacity-50"
              >
                Work it out
              </button>
              {tried ? <span className="pb-1 text-[13px] font-semibold text-ink-900">{tried}</span> : null}
            </div>
          </details>
        </div>
      )}
    </div>
  );
}
