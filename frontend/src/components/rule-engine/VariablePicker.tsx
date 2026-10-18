"use client";

import Link from "next/link";
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

// Spreadsheet spellings. Capitals do not matter when typing.
const FUNCTIONS = [
  { key: "IF(condition, value_if_true, value_if_false)", label: "IF" },
  { key: "AND(a, b)", label: "AND" },
  { key: "OR(a, b)", label: "OR" },
  { key: "MIN(a, b)", label: "MIN" },
  { key: "MAX(a, b)", label: "MAX" },
  { key: "ROUND_HALF_UP(x)", label: "ROUND" },
  { key: "ROUNDUP(x, 0)", label: "ROUNDUP" },
  { key: "ROUNDDOWN(x, 0)", label: "ROUNDDOWN" },
];

type Variable = { key: string; label: string };

type Props = {
  onInsert: (snippet: string) => void;
  variables?: Variable[];
  /** This company's own salary components. */
  components?: Variable[];
};

export function VariablePicker({ onInsert, variables = DEFAULT_VARIABLES, components = [] }: Props) {
  return (
    <Card>
      <CardHeader>
        <p className="font-display text-[11px] font-semibold text-ink-500">
          Library
        </p>
        <CardTitle>Variables</CardTitle>
        <p className="text-xs text-ink-500">Click to insert at cursor.</p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <p className="mb-2 font-display text-[11px] font-semibold text-ink-500">
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
          <p className="mb-2 font-display text-[11px] font-semibold text-ink-500">
            Your salary components
          </p>
          {components.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {components.map((v) => (
                <Button
                  key={v.key}
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => onInsert(v.key)}
                  className="text-xs"
                  title={`Insert ${v.key}`}
                >
                  {v.label}
                </Button>
              ))}
            </div>
          ) : (
            <p className="text-xs text-ink-500">
              None yet. Components you add under{" "}
              <Link href="/config/components" className="font-semibold text-brand-700 hover:text-brand-800">
                Salary components
              </Link>{" "}
              appear here and can be used in formulas.
            </p>
          )}
        </div>
        <div>
          <p className="mb-2 font-display text-[11px] font-semibold text-ink-500">
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
