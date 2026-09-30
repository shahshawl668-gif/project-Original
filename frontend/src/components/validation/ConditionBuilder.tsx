"use client";

import { Plus, Trash2 } from "lucide-react";

import {
  OPERATOR_LABEL, isGroup,
  type Catalog, type Comparison, type Group, type Operand, type Operator, type Source,
} from "@/lib/matrix";
import { cn } from "@/lib/utils";

export const INPUT =
  "w-full rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900 focus:border-brand-500 focus:outline-none";

export const BLANK: Comparison = {
  left: { source: "field", key: "lop_days" },
  operator: "lte",
  right: { source: "literal", value: "0" },
  tolerance: "0",
};

const SOURCE_LABEL: Record<Source, string> = {
  field: "Payroll field",
  component: "Salary component",
  deduction: "Deduction",
  literal: "Fixed value",
  previous: "Last month's value",
  master: "Employee master",
  expr: "Calculation",
};

function keysFor(source: Source, of: Operand["of"], catalog: Catalog): string[] {
  const kind = source === "previous" ? of ?? "field" : source;
  if (kind === "component") return catalog.components;
  if (kind === "deduction") return catalog.deductions;
  if (kind === "master") return catalog.master_fields;
  return catalog.fields;
}

export function OperandEditor({ label, value, onChange, catalog, advanced }: {
  label: string; value: Operand; onChange: (value: Operand) => void; catalog: Catalog; advanced: boolean;
}) {
  const sources: Source[] = advanced
    ? ["field", "component", "deduction", "literal", "previous", "master", "expr"]
    : ["field", "component", "deduction", "literal"];
  const options = keysFor(value.source, value.of, catalog);
  return (
    <div className="space-y-1">
      <span className="text-xs font-semibold text-ink-700">{label}</span>
      <div className="grid gap-2 sm:grid-cols-2">
        <select aria-label={`${label} source`} className={INPUT} value={value.source} onChange={(e) => {
          const source = e.target.value as Source;
          if (source === "literal") onChange({ source, value: "" });
          else if (source === "expr") onChange({ source, value: "" });
          else if (source === "previous") onChange({ source, of: "field", key: catalog.fields[0] ?? "" });
          else onChange({ source, key: keysFor(source, undefined, catalog)[0] ?? "" });
        }}>
          {sources.map((s) => <option key={s} value={s}>{SOURCE_LABEL[s]}</option>)}
        </select>
        {value.source === "literal" ? (
          <input aria-label={`${label} fixed value`} className={INPUT} value={value.value ?? ""}
            onChange={(e) => onChange({ source: "literal", value: e.target.value })} placeholder="Amount or text" />
        ) : value.source === "expr" ? (
          <input aria-label={`${label} calculation`} className={cn(INPUT, "font-mono")} value={value.value ?? ""}
            onChange={(e) => onChange({ source: "expr", value: e.target.value })} placeholder="basic / gross * 100" />
        ) : (
          <div className="flex gap-2">
            {value.source === "previous" ? (
              <select aria-label={`${label} kind`} className={cn(INPUT, "max-w-32")} value={value.of ?? "field"}
                onChange={(e) => {
                  const of = e.target.value as Operand["of"];
                  onChange({ source: "previous", of, key: keysFor("previous", of, catalog)[0] ?? "" });
                }}>
                <option value="field">field</option>
                <option value="component">component</option>
                <option value="deduction">deduction</option>
              </select>
            ) : null}
            <select aria-label={`${label} selection`} className={INPUT} value={value.key ?? ""}
              onChange={(e) => onChange({ ...value, key: e.target.value })}>
              {!options.length && <option value="">Configure a component first</option>}
              {options.map((k) => <option key={k} value={k}>{k.replaceAll("_", " ")}</option>)}
            </select>
          </div>
        )}
      </div>
      {value.source === "expr" ? (
        <p className="text-[11px] text-ink-500">
          Use + − × ÷, brackets, min, max, abs, round, floor, ceil. Names: numeric fields, deductions and
          components (e.g. {catalog.expression_variables.filter((v) => !v.startsWith("prev_")).slice(0, 4).join(", ")}),
          and prev_ of any of them for last month. A missing value or a division by zero means “cannot validate”.
        </p>
      ) : null}
    </div>
  );
}

export function ComparisonEditor({ title, value, onChange, catalog, advanced, onRemove }: {
  title: string; value: Comparison; onChange: (value: Comparison) => void; catalog: Catalog; advanced: boolean;
  onRemove?: () => void;
}) {
  return (
    <div className="space-y-3 rounded-xl border border-ink-200 bg-ink-50/50 p-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ink-900">{title}</h3>
        {onRemove ? (
          <button type="button" onClick={onRemove} className="text-xs font-semibold text-ink-500 hover:text-danger-700" aria-label={`Remove ${title}`}>
            <Trash2 size={14} />
          </button>
        ) : null}
      </div>
      <div className="grid gap-3 lg:grid-cols-[1fr_11rem_1fr]">
        <OperandEditor label="Check this" value={value.left} onChange={(left) => onChange({ ...value, left })} catalog={catalog} advanced={advanced} />
        <label className="text-xs font-semibold text-ink-700">Comparison
          <select className={`mt-1 ${INPUT}`} value={value.operator}
            onChange={(e) => onChange({ ...value, operator: e.target.value as Operator })}>
            {Object.entries(OPERATOR_LABEL).map(([k, text]) => <option key={k} value={k}>{text}</option>)}
          </select>
        </label>
        {value.operator === "present" ? (
          <p className="self-end text-xs text-ink-500">Checks that the selected value exists.</p>
        ) : (
          <OperandEditor
            label={value.operator === "in" || value.operator === "not_in" ? "Allowed list (use | between values)" : "Against this"}
            value={value.right} onChange={(right) => onChange({ ...value, right })} catalog={catalog}
            advanced={advanced && value.operator !== "in" && value.operator !== "not_in"} />
        )}
      </div>
      <label className="block max-w-[11rem] text-xs font-semibold text-ink-700">Allowed difference
        <input className={`mt-1 ${INPUT}`} inputMode="decimal" value={value.tolerance}
          onChange={(e) => onChange({ ...value, tolerance: e.target.value })} />
      </label>
    </div>
  );
}

/** A nested AND/OR group. Depth and size limits come from the server's catalogue. */
export function GroupEditor({ value, onChange, catalog, depth = 1, onRemove }: {
  value: Group; onChange: (value: Group) => void; catalog: Catalog; depth?: number; onRemove?: () => void;
}) {
  const set = (i: number, next: Comparison | Group) =>
    onChange({ ...value, items: value.items.map((x, j) => (j === i ? next : x)) });
  const remove = (i: number) => onChange({ ...value, items: value.items.filter((_, j) => j !== i) });
  return (
    <div className={cn("space-y-3 rounded-xl border-l-4 p-3",
      value.mode === "all" ? "border-brand-400 bg-brand-50/40" : "border-warning-400 bg-warning-50/40")}>
      <div className="flex flex-wrap items-center gap-2 text-xs font-semibold text-ink-700">
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={value.negate} onChange={(e) => onChange({ ...value, negate: e.target.checked })} /> NOT
        </label>
        <select aria-label={`Group ${depth} joins`} className={cn(INPUT, "w-auto py-1")} value={value.mode}
          onChange={(e) => onChange({ ...value, mode: e.target.value as Group["mode"] })}>
          <option value="all">ALL of these (AND)</option>
          <option value="any">ANY of these (OR)</option>
        </select>
        <button type="button" onClick={() => onChange({ ...value, items: [...value.items, { ...BLANK }] })}
          className="inline-flex items-center gap-1 rounded-lg border border-brand-300 px-2 py-1 text-brand-700">
          <Plus size={12} /> Condition
        </button>
        {depth < catalog.limits.max_depth ? (
          <button type="button"
            onClick={() => onChange({ ...value, items: [...value.items, { mode: "any", negate: false, items: [{ ...BLANK }] }] })}
            className="inline-flex items-center gap-1 rounded-lg border border-brand-300 px-2 py-1 text-brand-700">
            <Plus size={12} /> Group
          </button>
        ) : null}
        {onRemove ? (
          <button type="button" onClick={onRemove} className="ml-auto text-ink-500 hover:text-danger-700" aria-label="Remove group">
            <Trash2 size={14} />
          </button>
        ) : null}
      </div>
      {value.items.map((item, i) => isGroup(item) ? (
        <GroupEditor key={i} value={item} onChange={(n) => set(i, n)} catalog={catalog} depth={depth + 1}
          onRemove={() => remove(i)} />
      ) : (
        <ComparisonEditor key={i} title={`Condition ${i + 1}`} value={item} onChange={(n) => set(i, n)}
          catalog={catalog} advanced onRemove={value.items.length > 1 ? () => remove(i) : undefined} />
      ))}
    </div>
  );
}
