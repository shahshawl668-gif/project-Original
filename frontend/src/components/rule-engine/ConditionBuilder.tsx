"use client";

import { Trash2, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Condition, ConditionOperator } from "@/lib/rule-engine";

const OPERATORS: ConditionOperator[] = [">", "<", ">=", "<=", "==", "!="];

const FIELDS = [
  "basic",
  "da",
  "hra",
  "gross",
  "pf_wage",
  "esic_wage",
  "ctc_monthly",
  "paid_days",
  "lop_days",
];

type Props = {
  conditions: Condition[];
  onChange: (next: Condition[]) => void;
  fields?: string[];
};

export function ConditionBuilder({ conditions, onChange, fields = FIELDS }: Props) {
  const update = (idx: number, patch: Partial<Condition>) => {
    const next = conditions.map((c, i) => (i === idx ? { ...c, ...patch } : c));
    onChange(next);
  };

  const remove = (idx: number) => onChange(conditions.filter((_, i) => i !== idx));

  const add = () =>
    onChange([...conditions, { field: fields[0] ?? "gross", operator: "<=", value: 0 }]);

  return (
    <div className="space-y-2.5">
      {conditions.length === 0 && (
        <p className="rounded-xl border border-dashed border-ink-200 bg-ink-50/40 px-4 py-3 text-xs text-ink-500 dark:border-white/[0.07] dark:bg-white/[0.02] dark:text-ink-400">
          No conditions. Formula will always apply. Add a condition to gate it.
        </p>
      )}
      {conditions.map((c, idx) => (
        <div
          key={idx}
          className="flex flex-wrap items-center gap-2 rounded-xl border border-ink-200 bg-white p-2 shadow-sm dark:border-white/[0.07] dark:bg-white/[0.03]"
        >
          <Select value={c.field} onValueChange={(v) => update(idx, { field: v })}>
            <SelectTrigger className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {fields.map((f) => (
                <SelectItem key={f} value={f}>
                  {f}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select
            value={c.operator}
            onValueChange={(v) => update(idx, { operator: v as ConditionOperator })}
          >
            <SelectTrigger className="w-24">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {OPERATORS.map((o) => (
                <SelectItem key={o} value={o}>
                  {o}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Input
            type="number"
            step="0.01"
            value={c.value}
            onChange={(e) => update(idx, { value: Number(e.target.value) })}
            className="w-32"
          />

          <Button type="button" variant="ghost" size="icon" onClick={() => remove(idx)}>
            <Trash2 className="h-4 w-4 text-danger-600 dark:text-danger-400" />
          </Button>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" onClick={add}>
        <Plus className="h-3.5 w-3.5" /> Add condition
      </Button>
    </div>
  );
}
