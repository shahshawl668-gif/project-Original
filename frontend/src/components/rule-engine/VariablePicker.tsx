"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const DEFAULT_VARIABLES = [
  { key: "basic", label: "Basic" },
  { key: "da", label: "DA" },
  { key: "hra", label: "HRA" },
  { key: "gross", label: "Gross" },
  { key: "pf_wage", label: "PF Wage" },
  { key: "esic_wage", label: "ESIC Wage" },
  { key: "ctc_monthly", label: "CTC (Monthly)" },
  { key: "paid_days", label: "Paid Days" },
  { key: "lop_days", label: "LOP Days" },
  { key: "total_days", label: "Total Days" },
];

const FUNCTIONS = [
  { key: "min(a, b)", label: "min" },
  { key: "max(a, b)", label: "max" },
  { key: "round(x)", label: "round" },
  { key: "if(cond, a, b)", label: "if" },
];

type Props = {
  onInsert: (snippet: string) => void;
  variables?: { key: string; label: string }[];
};

export function VariablePicker({ onInsert, variables = DEFAULT_VARIABLES }: Props) {
  return (
    <Card>
      <CardHeader>
        <p className="font-display text-[11px] font-bold uppercase tracking-[0.14em] text-ink-500 dark:text-ink-300">
          Library
        </p>
        <CardTitle>Variables</CardTitle>
        <p className="text-xs text-ink-500 dark:text-ink-400">Click to insert at cursor.</p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <p className="mb-2 font-display text-[11px] font-bold uppercase tracking-[0.12em] text-ink-500 dark:text-ink-300">
            Inputs
          </p>
          <div className="flex flex-wrap gap-1.5">
            {variables.map((v) => (
              <Button
                key={v.key}
                type="button"
                variant="outline"
                size="sm"
                onClick={() => onInsert(v.key)}
                className="text-xs"
              >
                {v.label}
              </Button>
            ))}
          </div>
        </div>
        <div>
          <p className="mb-2 font-display text-[11px] font-bold uppercase tracking-[0.12em] text-ink-500 dark:text-ink-300">
            Functions
          </p>
          <div className="flex flex-wrap gap-1.5">
            {FUNCTIONS.map((v) => (
              <Button
                key={v.key}
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => onInsert(v.key)}
                className="text-xs"
              >
                {v.label}
              </Button>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
