"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { testFormula, type Condition, type TestFormulaResult } from "@/lib/rule-engine";

const TEST_VARS = ["basic", "da", "hra", "gross", "pf_wage", "esic_wage"];

type Props = {
  expression: string;
  conditions: Condition[];
};

export function FormulaTester({ expression, conditions }: Props) {
  const [vars, setVars] = useState<Record<string, string>>({
    basic: "15000",
    da: "0",
    hra: "6000",
    gross: "25000",
    pf_wage: "15000",
    esic_wage: "20000",
  });
  const [result, setResult] = useState<TestFormulaResult | null>(null);
  const [loading, setLoading] = useState(false);

  const handleTest = async () => {
    if (!expression.trim()) {
      toast.error("Write a formula first");
      return;
    }
    setLoading(true);
    try {
      const numericVars: Record<string, number> = {};
      for (const [k, v] of Object.entries(vars)) numericVars[k] = Number(v) || 0;
      const r = await testFormula({ expression, conditions, variables: numericVars });
      setResult(r);
      if (!r.ok) toast.error(r.error || "Formula error");
      else if (r.conditions_passed === false)
        toast("Conditions did not match — result is 0", { description: "Adjust inputs or conditions." });
      else toast.success(`Result: ${r.result}`);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <p className="font-display text-[11px] font-bold uppercase tracking-[0.14em] text-ink-500 dark:text-ink-300">
          Sandbox
        </p>
        <CardTitle>Formula tester</CardTitle>
        <p className="text-xs text-ink-500 dark:text-ink-400">
          Provide sample inputs and run the formula end-to-end.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-2.5">
          {TEST_VARS.map((k) => (
            <div key={k} className="space-y-1">
              <Label htmlFor={`var-${k}`} className="text-xs">
                {k}
              </Label>
              <Input
                id={`var-${k}`}
                type="number"
                value={vars[k] ?? ""}
                onChange={(e) => setVars((p) => ({ ...p, [k]: e.target.value }))}
              />
            </div>
          ))}
        </div>
        <Button type="button" onClick={handleTest} disabled={loading} className="w-full">
          {loading ? "Testing…" : "Test formula"}
        </Button>
        {result && (
          <div className="rounded-xl border border-ink-200 bg-ink-50/50 p-4 text-sm dark:border-white/[0.07] dark:bg-white/[0.03]">
            {result.ok ? (
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="font-display text-[11px] font-bold uppercase tracking-[0.14em] text-ink-500 dark:text-ink-300">
                    Computed value
                  </p>
                  <p className="font-display text-2xl font-bold tracking-tight text-ink-900 dark:text-white">
                    {(result.result ?? 0).toLocaleString(undefined, {
                      maximumFractionDigits: 2,
                    })}
                  </p>
                </div>
                <Badge variant={result.conditions_passed === false ? "secondary" : "success"}>
                  {result.conditions_passed === false ? "Skipped (conditions)" : "Applied"}
                </Badge>
              </div>
            ) : (
              <div className="text-sm text-danger-700 dark:text-danger-300">{result.error}</div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
