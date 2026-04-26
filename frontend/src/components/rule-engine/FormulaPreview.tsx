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
    <div className="rounded-md bg-brand-50 border border-brand-100 px-3 py-2 text-sm text-brand-800">
      <span className="font-medium">Preview:</span> {describe(expression, ruleType)}
    </div>
  );
}
