"use client";

import type { FormulaRuleType } from "@/lib/rule-engine";

const PREVIEW_HINTS: Record<string, string> = {
  "min(pf_wage, 15000) * 0.12": "PF = 12% of min(pf_wage, 15000)",
  "min(pf_wage, 15000) * 0.0833": "EPS = 8.33% of min(pf_wage, 15000)",
  "gross * 0.0075": "ESIC EE = 0.75% of gross",
  "gross * 0.0325": "ESIC ER = 3.25% of gross",
};

function describe(expression: string, ruleType: FormulaRuleType): string {
  const trimmed = expression.trim();
  if (PREVIEW_HINTS[trimmed]) return PREVIEW_HINTS[trimmed];
  // Best-effort: turn `* 0.12` into a percent for human reading.
  const pct = trimmed.match(/\*\s*0?\.(\d+)/);
  if (pct) {
    const percent = (parseFloat("0." + pct[1]) * 100).toFixed(2).replace(/\.00$/, "");
    return `${ruleType} ≈ ${percent}% of (${trimmed.replace(pct[0], "").trim() || "wage"})`;
  }
  return `${ruleType} = ${trimmed}`;
}

export function FormulaPreview({
  expression,
  ruleType,
}: {
  expression: string;
  ruleType: FormulaRuleType;
}) {
  if (!expression.trim()) return null;
  return (
    <div className="rounded-xl border border-brand-200 bg-brand-50/70 px-3.5 py-2.5 text-sm text-brand-900 shadow-sm dark:border-brand-500/20 dark:bg-brand-500/[0.08] dark:text-brand-100">
      <span className="font-display text-[11px] font-bold uppercase tracking-[0.14em] text-brand-700 dark:text-brand-300">
        Preview
      </span>
      <span className="ml-2 align-middle">{describe(expression, ruleType)}</span>
    </div>
  );
}
