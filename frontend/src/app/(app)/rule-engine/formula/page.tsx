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
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
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
  getFormulaVariables,
  testFormula,
  type FormulaVariables,
} from "@/lib/rule-engine";

const RULE_TYPES: FormulaRuleType[] = ["PF", "ESIC"];

const PRESETS: Record<FormulaRuleType, string> = {
  PF: "MIN(pf_wage, 15000) * 12%",
  ESIC: "IF(gross <= 21000, ROUNDUP(gross * 0.75%, 0), 0)",
};

/**
 * How companies commonly define the wage and the cap. Clicking one puts it in
 * the editor; the numbers are examples — change the ceiling, rate or limit to
 * your own. A pattern that names a salary component (special_allowance) only
 * validates once that component exists under Salary components.
 */
const PATTERNS: Record<FormulaRuleType, { title: string; note: string; expression: string }[]> = {
  PF: [
    { title: "PF wage up to a ceiling", note: "12% of the PF wage, counting at most the ceiling.", expression: "MIN(pf_wage, 15000) * 12%" },
    { title: "Basic × rate", note: "12% of Basic for everyone, no cap.", expression: "basic * 12%" },
    { title: "Basic × rate, with a maximum", note: "12% of Basic but never more than a fixed amount.", expression: "MIN(basic * 12%, 3000)" },
    {
      title: "Lower-paid employees use Basic + components",
      note: "Basic at or below the limit: Basic + chosen components, capped. Above it: Basic × 12%. Swap special_allowance for any of your components.",
      expression: "IF(basic <= 25000, MIN((basic + special_allowance) * 12%, 3000), basic * 12%)",
    },
  ],
  ESIC: [
    { title: "On ESIC wage, rounded up", note: "0.75% of the ESIC wage up to the limit, rounded up to the next rupee; 0 above it.", expression: "IF(esic_wage <= 21000, ROUNDUP(esic_wage * 0.75%, 0), 0)" },
    { title: "On gross, rounded to the nearest rupee", note: "Same, on gross, rounded to the nearest rupee.", expression: "IF(gross <= 21000, ROUND_HALF_UP(gross * 0.75%), 0)" },
    { title: "On selected components", note: "ESIC wage is the sum of components you choose. Swap in your own.", expression: "IF((basic + hra + special_allowance) <= 21000, ROUNDUP((basic + hra + special_allowance) * 0.75%, 0), 0)" },
  ],
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
  const [variables, setVariables] = useState<FormulaVariables | null>(null);
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

  useEffect(() => {
    getFormulaVariables().then(setVariables).catch(() => setVariables(null));
  }, []);

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
    <div className="space-y-8">
      <PageHeader
        eyebrow="Rule engine"
        title="Formula builder"
        description="Define dynamic PF / ESIC computation logic. Versions are immutable and can be rolled back at any time."
        actions={
          <div className="flex items-end gap-2">
            <div className="space-y-1.5">
              <Label className="text-[11px]">Rule type</Label>
              <Select value={ruleType} onValueChange={handleRuleTypeChange}>
                <SelectTrigger className="w-36">
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
        }
      />

      <AlertBanner variant="info" title="Where saved formulas are used">
        Formulas are saved as versions you can test and roll back here. Payroll validation
        currently works out PF and ESIC from the Statutory engine settings (wage components,
        ceilings, rates, rounding), not from a saved formula.
      </AlertBanner>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader>
              <p className="font-display text-[11px] font-semibold text-ink-500">
                Definition
              </p>
              <CardTitle>Expression</CardTitle>
              <p className="text-xs text-ink-500">
                Write it like an Excel formula — capital letters don&apos;t matter, and{" "}
                <span className="font-mono">12%</span> means 12 percent. You can use{" "}
                <span className="font-mono">+ - * / ^</span>, brackets, comparisons{" "}
                <span className="font-mono">= &lt;&gt; &lt; &gt; &lt;= &gt;=</span>, and{" "}
                <span className="font-mono">IF AND OR MIN MAX ROUNDUP ROUNDDOWN</span>, with the
                variables on the right — including your own salary components. A name with spaces
                can be written <span className="font-mono">[Special Allowance]</span>.
              </p>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="formula-name">Name (optional)</Label>
                <Input
                  id="formula-name"
                  placeholder="e.g. PF — Basic + special allowance up to 25,000"
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
                <AlertBanner variant="error" title="This formula needs fixing">
                  {syntaxError}
                </AlertBanner>
              )}
              <FormulaPreview expression={expression} ruleType={ruleType} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <p className="font-display text-[11px] font-semibold text-ink-500">
                Starting points
              </p>
              <CardTitle>How companies usually define {ruleType}</CardTitle>
              <p className="text-xs text-ink-500">
                Click one to load it, then change the numbers and components to match your policy.
              </p>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2">
              {PATTERNS[ruleType].map((p) => (
                <button
                  key={p.title}
                  type="button"
                  onClick={() => setExpression(p.expression)}
                  className="rounded-xl border border-ink-200 p-3 text-left transition-colors hover:border-brand-300 hover:bg-brand-50/50"
                >
                  <span className="block text-sm font-semibold text-ink-900">{p.title}</span>
                  <span className="mt-0.5 block text-xs text-ink-500">{p.note}</span>
                  <code className="mt-2 block break-words text-[11px] text-ink-700">{p.expression}</code>
                </button>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <p className="font-display text-[11px] font-semibold text-ink-500">
                Eligibility
              </p>
              <CardTitle>Conditions</CardTitle>
              <p className="text-xs text-ink-500">
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
              {saving ? "Saving…" : "Save & activate"}
            </Button>
          </div>

          <VersionPanel
            formulas={filteredFormulas}
            onChanged={refreshFormulas}
            onLoad={handleLoadVersion}
          />
        </div>

        <div className="space-y-6">
          <VariablePicker
            onInsert={(s) => editorRef.current?.insertAtCursor(s)}
            variables={variables?.inputs}
            components={variables?.components}
          />
          <FormulaTester
            expression={expression}
            conditions={conditions}
            componentKeys={variables?.components.map((c) => c.key)}
          />
        </div>
      </div>
    </div>
  );
}
