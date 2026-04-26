"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { z } from "zod";
import { toast } from "sonner";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import FormulaEditor, {
  type FormulaEditorHandle,
} from "@/components/rule-engine/FormulaEditor";
import { VariablePicker } from "@/components/rule-engine/VariablePicker";
import { ConditionBuilder } from "@/components/rule-engine/ConditionBuilder";
import { FormulaTester } from "@/components/rule-engine/FormulaTester";
import { VersionPanel } from "@/components/rule-engine/VersionPanel";
import { FormulaPreview } from "@/components/rule-engine/FormulaPreview";
import {
  type Condition,
  type Formula,
  type FormulaRuleType,
  createFormula,
  getFormulas,
  testFormula,
} from "@/lib/rule-engine";

const RULE_TYPES: FormulaRuleType[] = ["PF", "ESIC"];

const PRESETS: Record<FormulaRuleType, string> = {
  PF: "min(pf_wage, 15000) * 0.12",
  ESIC: "if(gross <= 21000, gross * 0.0075, 0)",
};

const formulaSchema = z.object({
  rule_type: z.enum(["PF", "ESIC"]),
  name: z.string().max(120).optional().nullable(),
  expression: z.string().min(1, "Formula is required"),
});

export default function FormulaPage() {
  const editorRef = useRef<FormulaEditorHandle | null>(null);
  const [ruleType, setRuleType] = useState<FormulaRuleType>("PF");
  const [name, setName] = useState("");
  const [expression, setExpression] = useState(PRESETS.PF);
  const [conditions, setConditions] = useState<Condition[]>([]);
  const [formulas, setFormulas] = useState<Formula[]>([]);
  const [syntaxError, setSyntaxError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const refreshFormulas = useCallback(async () => {
    try {
      const list = await getFormulas();
      setFormulas(list);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void refreshFormulas();
  }, [refreshFormulas]);

  // Live syntax check (debounced)
  useEffect(() => {
    if (!expression.trim()) {
      setSyntaxError(null);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const r = await testFormula({ expression, conditions: [], variables: {} });
        setSyntaxError(r.ok ? null : r.error);
      } catch {
        setSyntaxError(null);
      }
    }, 400);
    return () => clearTimeout(t);
  }, [expression, conditions]);

  const filteredFormulas = useMemo(
    () => formulas.filter((f) => f.rule_type === ruleType),
    [formulas, ruleType]
  );

  const handleRuleTypeChange = (v: string) => {
    const rt = v as FormulaRuleType;
    setRuleType(rt);
    if (!expression.trim() || expression === PRESETS.PF || expression === PRESETS.ESIC) {
      setExpression(PRESETS[rt]);
    }
  };

  const handleSave = async () => {
    const parsed = formulaSchema.safeParse({ rule_type: ruleType, name, expression });
    if (!parsed.success) {
      toast.error(parsed.error.issues[0]?.message ?? "Invalid formula");
      return;
    }
    if (syntaxError) {
      toast.error("Fix syntax errors before saving");
      return;
    }
    setSaving(true);
    try {
      const created = await createFormula({
        rule_type: ruleType,
        name: name || null,
        expression,
        conditions,
        activate: true,
      });
      toast.success(`Saved v${created.version} (active)`);
      await refreshFormulas();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const handleLoadVersion = (f: Formula) => {
    setRuleType(f.rule_type);
    setName(f.name ?? "");
    setExpression(f.expression);
    setConditions(f.conditions ?? []);
    toast(`Loaded v${f.version}`);
  };

  const saveDisabled = saving || !!syntaxError || !expression.trim();

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Formula Builder</h1>
          <p className="text-sm text-slate-600">
            Define dynamic PF / ESIC computation logic. Versions are immutable.
          </p>
        </div>
        <div className="flex gap-2">
          <div className="space-y-1">
            <Label>Rule Type</Label>
            <Select value={ruleType} onValueChange={handleRuleTypeChange}>
              <SelectTrigger className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {RULE_TYPES.map((rt) => (
                  <SelectItem key={rt} value={rt}>
                    {rt}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Expression</CardTitle>
              <p className="text-xs text-slate-500">
                Allowed: + - * / %, parentheses, min, max, round, if(cond, a, b), and the listed
                variables.
              </p>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="space-y-1">
                <Label htmlFor="formula-name">Name (optional)</Label>
                <Input
                  id="formula-name"
                  placeholder="e.g. PF v1 — capped at 15000"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
              <FormulaEditor
                ref={editorRef}
                value={expression}
                onChange={setExpression}
                errorLine={syntaxError ? 1 : null}
                errorMessage={syntaxError}
              />
              {syntaxError && (
                <p className="text-xs text-red-600">{syntaxError}</p>
              )}
              <FormulaPreview expression={expression} ruleType={ruleType} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Conditions</CardTitle>
              <p className="text-xs text-slate-500">
                If set, all conditions (AND) must pass for the formula to apply. Otherwise the
                contribution is 0.
              </p>
            </CardHeader>
            <CardContent>
              <ConditionBuilder conditions={conditions} onChange={setConditions} />
            </CardContent>
          </Card>

          <div className="flex items-center justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setExpression(PRESETS[ruleType]);
                setConditions([]);
              }}
            >
              Reset to default
            </Button>
            <Button type="button" onClick={handleSave} disabled={saveDisabled}>
              {saving ? "Saving…" : "Save & Activate"}
            </Button>
          </div>

          <VersionPanel
            formulas={filteredFormulas}
            onChanged={refreshFormulas}
            onLoad={handleLoadVersion}
          />
        </div>

        <div className="space-y-6">
          <VariablePicker onInsert={(s) => editorRef.current?.insertAtCursor(s)} />
          <FormulaTester expression={expression} conditions={conditions} />
        </div>
      </div>
    </div>
  );
}
