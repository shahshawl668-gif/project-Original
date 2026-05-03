"use client";

import { useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Frequency, Gender, SlabRow } from "@/lib/rule-engine";

const FREQUENCIES: Frequency[] = ["monthly", "yearly", "half-yearly", "quarterly"];
const GENDERS: Gender[] = ["ALL", "MALE", "FEMALE"];

function parseMonths(input: string): number[] | null {
  const trimmed = input.trim();
  if (!trimmed) return null;
  const parts = trimmed.split(/[,\s]+/).filter(Boolean);
  const out: number[] = [];
  for (const p of parts) {
    const n = Number(p);
    if (!Number.isInteger(n) || n < 1 || n > 12) {
      throw new Error(`"${p}" is not a month between 1 and 12`);
    }
    if (!out.includes(n)) out.push(n);
  }
  out.sort((a, b) => a - b);
  return out.length ? out : null;
}

function monthsToInput(months: number[] | null | undefined): string {
  return months && months.length ? months.join(",") : "";
}

export const slabRowSchema = z
  .object({
    min_salary: z.coerce.number().min(0, "min must be ≥ 0"),
    max_salary: z.coerce.number().min(0, "max must be ≥ 0"),
    deduction_amount: z.coerce.number().min(0, "amount must be ≥ 0"),
    employer_amount: z
      .union([z.coerce.number().min(0, "must be ≥ 0"), z.null()])
      .optional()
      .transform((v) => (v === undefined ? null : v)),
    frequency: z.enum(["monthly", "yearly", "half-yearly", "quarterly"]),
    gender: z.enum(["ALL", "MALE", "FEMALE"]),
    applicable_months: z
      .union([z.array(z.number().int().min(1).max(12)), z.null()])
      .optional()
      .transform((v) => (v && v.length ? v : null)),
  })
  .refine((s) => Number(s.min_salary) <= Number(s.max_salary), {
    message: "min_salary must be ≤ max_salary",
    path: ["min_salary"],
  });

export const slabsSchema = z.array(slabRowSchema).superRefine((rows, ctx) => {
  // Overlap is only meaningful within the same (gender, applicable_months) bucket;
  // a Feb-only top-up legitimately shares the wage band with the always-on row.
  type Bucketed = z.infer<typeof slabRowSchema> & { _idx: number };
  const buckets: Record<string, Bucketed[]> = {};
  rows.forEach((r, i) => {
    const months = r.applicable_months ? [...r.applicable_months].sort().join(",") : "";
    const key = `${r.gender}|${months}`;
    (buckets[key] ||= []).push({ ...r, _idx: i });
  });
  for (const arr of Object.values(buckets)) {
    arr.sort((a, b) => Number(a.min_salary) - Number(b.min_salary));
    let prevMax: number | null = null;
    for (const r of arr) {
      if (prevMax !== null && Number(r.min_salary) <= prevMax) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: [r._idx, "min_salary"],
          message: `Overlaps previous slab in same gender/month group (≤ ${prevMax})`,
        });
      }
      prevMax = Number(r.max_salary);
    }
  }
});

type RowError = Partial<Record<keyof SlabRow, string>>;

type Props = {
  slabs: SlabRow[];
  onChange: (next: SlabRow[]) => void;
  errors?: Record<number, RowError>;
  /** When true, render the Employer column (used for LWF). */
  showEmployer?: boolean;
};

export function SlabTable({ slabs, onChange, errors, showEmployer = false }: Props) {
  const [local, setLocal] = useState<SlabRow[]>(slabs);
  const [monthsText, setMonthsText] = useState<Record<number, string>>({});
  const [monthErrors, setMonthErrors] = useState<Record<number, string | null>>({});

  useEffect(() => {
    setLocal(slabs);
    const m: Record<number, string> = {};
    slabs.forEach((s, i) => (m[i] = monthsToInput(s.applicable_months)));
    setMonthsText(m);
    setMonthErrors({});
  }, [slabs]);

  const update = (idx: number, patch: Partial<SlabRow>) => {
    const next = local.map((r, i) => (i === idx ? { ...r, ...patch } : r));
    setLocal(next);
    onChange(next);
  };

  const updateMonths = (idx: number, value: string) => {
    setMonthsText((prev) => ({ ...prev, [idx]: value }));
    try {
      const parsed = parseMonths(value);
      setMonthErrors((prev) => ({ ...prev, [idx]: null }));
      update(idx, { applicable_months: parsed });
    } catch (e) {
      setMonthErrors((prev) => ({ ...prev, [idx]: (e as Error).message }));
    }
  };

  const remove = (idx: number) => {
    const next = local.filter((_, i) => i !== idx);
    setLocal(next);
    onChange(next);
    const nm: Record<number, string> = {};
    next.forEach((s, i) => (nm[i] = monthsToInput(s.applicable_months)));
    setMonthsText(nm);
    setMonthErrors({});
  };

  const add = () => {
    const last = local[local.length - 1];
    const nextMin = last ? Number(last.max_salary) + 1 : 0;
    const next: SlabRow[] = [
      ...local,
      {
        min_salary: nextMin,
        max_salary: nextMin + 10000,
        deduction_amount: 0,
        employer_amount: showEmployer ? 0 : null,
        frequency: "monthly",
        gender: "ALL",
        applicable_months: null,
      },
    ];
    setLocal(next);
    onChange(next);
    setMonthsText((prev) => ({ ...prev, [next.length - 1]: "" }));
  };

  return (
    <div className="space-y-3">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Min Salary</TableHead>
            <TableHead>Max Salary</TableHead>
            <TableHead>{showEmployer ? "Employee" : "Deduction"}</TableHead>
            {showEmployer && <TableHead>Employer</TableHead>}
            <TableHead>Frequency</TableHead>
            <TableHead>Gender</TableHead>
            <TableHead>Applicable months</TableHead>
            <TableHead className="w-12"></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {local.length === 0 && (
            <TableRow>
              <TableCell
                colSpan={showEmployer ? 8 : 7}
                className="py-8 text-center text-ink-500 dark:text-ink-400"
              >
                No slabs yet. Add your first row.
              </TableCell>
            </TableRow>
          )}
          {local.map((r, idx) => {
            const e = errors?.[idx];
            const monthErr = monthErrors[idx];
            return (
              <TableRow
                key={idx}
                className={
                  e || monthErr
                    ? "bg-danger-50/60 dark:bg-danger-500/[0.08]"
                    : undefined
                }
              >
                <TableCell>
                  <Input
                    type="number"
                    value={r.min_salary}
                    onChange={(ev) => update(idx, { min_salary: ev.target.value })}
                    className={e?.min_salary ? "border-danger-400 dark:border-danger-500/60" : ""}
                  />
                  {e?.min_salary && (
                    <p className="mt-1 text-xs text-danger-600 dark:text-danger-300">
                      {e.min_salary}
                    </p>
                  )}
                </TableCell>
                <TableCell>
                  <Input
                    type="number"
                    value={r.max_salary}
                    onChange={(ev) => update(idx, { max_salary: ev.target.value })}
                    className={e?.max_salary ? "border-danger-400 dark:border-danger-500/60" : ""}
                  />
                </TableCell>
                <TableCell>
                  <Input
                    type="number"
                    step="0.01"
                    value={r.deduction_amount}
                    onChange={(ev) => update(idx, { deduction_amount: ev.target.value })}
                    className={e?.deduction_amount ? "border-danger-400 dark:border-danger-500/60" : ""}
                  />
                </TableCell>
                {showEmployer && (
                  <TableCell>
                    <Input
                      type="number"
                      step="0.01"
                      value={r.employer_amount ?? 0}
                      onChange={(ev) => update(idx, { employer_amount: ev.target.value })}
                      className={e?.employer_amount ? "border-danger-400 dark:border-danger-500/60" : ""}
                    />
                    {e?.employer_amount && (
                      <p className="mt-1 text-xs text-danger-600 dark:text-danger-300">
                        {e.employer_amount}
                      </p>
                    )}
                  </TableCell>
                )}
                <TableCell>
                  <Select
                    value={r.frequency}
                    onValueChange={(v) => update(idx, { frequency: v as Frequency })}
                  >
                    <SelectTrigger className="w-32">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {FREQUENCIES.map((f) => (
                        <SelectItem key={f} value={f}>
                          {f}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </TableCell>
                <TableCell>
                  <Select
                    value={r.gender}
                    onValueChange={(v) => update(idx, { gender: v as Gender })}
                  >
                    <SelectTrigger className="w-28">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {GENDERS.map((g) => (
                        <SelectItem key={g} value={g}>
                          {g}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </TableCell>
                <TableCell>
                  <Input
                    placeholder="all months"
                    value={monthsText[idx] ?? ""}
                    onChange={(ev) => updateMonths(idx, ev.target.value)}
                    className={monthErr ? "border-danger-400 dark:border-danger-500/60" : ""}
                  />
                  {monthErr ? (
                    <p className="mt-1 text-xs text-danger-600 dark:text-danger-300">{monthErr}</p>
                  ) : (
                    <p className="mt-1 text-[10px] text-ink-400 dark:text-ink-500">
                      e.g. 2 (Feb only)
                    </p>
                  )}
                </TableCell>
                <TableCell>
                  <Button type="button" variant="ghost" size="icon" onClick={() => remove(idx)}>
                    <Trash2 className="h-4 w-4 text-danger-600 dark:text-danger-400" />
                  </Button>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      <Button type="button" variant="outline" size="sm" onClick={add}>
        <Plus className="h-3.5 w-3.5" /> Add slab
      </Button>
    </div>
  );
}
