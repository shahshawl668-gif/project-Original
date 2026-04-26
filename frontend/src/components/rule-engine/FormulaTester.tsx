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
        <CardTitle>Formula Tester</CardTitle>
        <p className="text-xs text-slate-500">
          Provide sample inputs and run the formula end-to-end.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-2">
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
          {loading ? "Testing…" : "Test Formula"}
        </Button>
        {result && (
          <div className="rounded-md border border-slate-200 p-3 text-sm">
            {result.ok ? (
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-slate-500 text-xs">Computed value</p>
                  <p className="text-xl font-semibold text-slate-900">
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
              <div className="text-red-700 text-sm">{result.error}</div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
