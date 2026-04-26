"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
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
import { SlabTable, slabsSchema } from "@/components/rule-engine/SlabTable";
import {
  type SlabRow,
  type SlabRuleType,
  getReferenceStates,
  getSlabs,
  importAllDefaultSlabs,
  importDefaultSlabs,
  listDefaultStates,
  resetDefaultSlabs,
  saveSlabs,
} from "@/lib/rule-engine";

const SLAB_TYPES: SlabRuleType[] = ["PT", "LWF"];

export default function SlabsPage() {
  const [ruleType, setRuleType] = useState<SlabRuleType>("PT");
  const [state, setState] = useState<string>("");
  const [stateOptions, setStateOptions] = useState<string[]>([]);
  const [customState, setCustomState] = useState("");
  const [slabs, setSlabs] = useState<SlabRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const [defaultsByType, setDefaultsByType] = useState<Record<SlabRuleType, string[]>>({
    PT: [],
    LWF: [],
  });
  const [errors, setErrors] = useState<Record<number, Record<string, string>>>({});

  const defaultStates = defaultsByType[ruleType] ?? [];

  useEffect(() => {
    (async () => {
      try {
        const [r, d] = await Promise.all([getReferenceStates(), listDefaultStates()]);
        setStateOptions(r.all_states);
        setDefaultsByType({ PT: d.PT, LWF: d.LWF });
        if (!state && r.all_states[0]) setState(r.all_states[0]);
      } catch (e) {
        toast.error((e as Error).message);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadSlabs = useCallback(async () => {
    if (!state) return;
    setLoading(true);
    try {
      const r = await getSlabs(state, ruleType);
      setSlabs(
        r.slabs.map((s) => ({
          min_salary: Number(s.min_salary),
          max_salary: Number(s.max_salary),
          deduction_amount: Number(s.deduction_amount),
          employer_amount:
            s.employer_amount === null || s.employer_amount === undefined
              ? null
              : Number(s.employer_amount),
          frequency: s.frequency,
          gender: s.gender ?? "ALL",
          applicable_months: s.applicable_months ?? null,
        }))
      );
      setErrors({});
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [state, ruleType]);

  useEffect(() => {
    void loadSlabs();
  }, [loadSlabs]);

  const validate = (rows: SlabRow[]): boolean => {
    const parsed = slabsSchema.safeParse(rows);
    if (parsed.success) {
      setErrors({});
      return true;
    }
    const next: Record<number, Record<string, string>> = {};
    for (const issue of parsed.error.issues) {
      const [idx, field] = issue.path;
      if (typeof idx === "number") {
        next[idx] = next[idx] || {};
        next[idx][String(field ?? "min_salary")] = issue.message;
      }
    }
    setErrors(next);
    return false;
  };

  const handleSave = async () => {
    if (!state) {
      toast.error("Pick or type a state first");
      return;
    }
    if (!validate(slabs)) {
      toast.error("Fix slab errors before saving");
      return;
    }
    setSaving(true);
    try {
      await saveSlabs({ state, rule_type: ruleType, slabs });
      toast.success(`Saved ${slabs.length} ${ruleType} slabs for ${state}`);
      await loadSlabs();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const handleImportCurrent = async () => {
    if (!state) {
      toast.error("Pick a state first");
      return;
    }
    if (!defaultStates.includes(state)) {
      toast.error(`No ${ruleType} defaults for ${state}. Available: ${defaultStates.join(", ")}`);
      return;
    }
    if (slabs.length && !confirm(`Replace existing ${ruleType} slabs for ${state}?`)) return;
    setImporting(true);
    try {
      const r = await importDefaultSlabs(state, ruleType, true);
      setSlabs(
        r.slabs.map((s) => ({
          min_salary: Number(s.min_salary),
          max_salary: Number(s.max_salary),
          deduction_amount: Number(s.deduction_amount),
          employer_amount:
            s.employer_amount === null || s.employer_amount === undefined
              ? null
              : Number(s.employer_amount),
          frequency: s.frequency,
          gender: s.gender ?? "ALL",
          applicable_months: s.applicable_months ?? null,
        }))
      );
      toast.success(`Imported ${r.slabs.length} default ${ruleType} slabs for ${state}`);
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setImporting(false);
    }
  };

  const handleResetAll = async () => {
    if (
      !confirm(
        `Wipe ALL existing ${ruleType} slabs for this tenant and re-import the curated India catalog (${defaultStates.length} states)? This cannot be undone.`
      )
    )
      return;
    setImporting(true);
    try {
      const r = await resetDefaultSlabs(ruleType);
      toast.success(
        `Reset complete — deleted ${r.deleted_rows} row(s), seeded ${r.total_states} state(s).`
      );
      const [refreshed, defaults] = await Promise.all([
        getReferenceStates(),
        listDefaultStates(),
      ]);
      setStateOptions(refreshed.all_states);
      setDefaultsByType({ PT: defaults.PT, LWF: defaults.LWF });
      const firstSeeded = Object.keys(r.imported)[0];
      if (firstSeeded) setState(firstSeeded);
      else await loadSlabs();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setImporting(false);
    }
  };

  const handleImportAll = async () => {
    if (
      !confirm(
        `Import ${ruleType} defaults for ALL supported states? Existing tenant slabs for these states will be kept (only empty states get seeded).`
      )
    )
      return;
    setImporting(true);
    try {
      const r = await importAllDefaultSlabs(ruleType, false);
      const seeded = Object.entries(r.imported).filter(([, n]) => n > 0).length;
      const skipped = Object.keys(r.imported).length - seeded;
      toast.success(`Seeded ${seeded} state(s); ${skipped} already had data.`);
      const refreshed = await getReferenceStates();
      setStateOptions(refreshed.all_states);
      const firstSeeded = Object.entries(r.imported).find(([, n]) => n > 0)?.[0];
      if (firstSeeded && (!state || !defaultStates.includes(state))) {
        setState(firstSeeded);
      } else {
        await loadSlabs();
      }
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setImporting(false);
    }
  };

  const useCustomState = () => {
    if (!customState.trim()) return;
    const s = customState.trim();
    setStateOptions((prev) => (prev.includes(s) ? prev : [...prev, s].sort()));
    setState(s);
    setCustomState("");
  };

  const sumPreview = useMemo(() => {
    return slabs.reduce((acc, s) => acc + Number(s.deduction_amount || 0), 0);
  }, [slabs]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">State Slab Configuration</h1>
        <p className="text-sm text-slate-600">
          Manage state-wise PT &amp; LWF slabs. These override seeded reference data when present.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="space-y-1">
              <Label>Rule Type</Label>
              <Select value={ruleType} onValueChange={(v) => setRuleType(v as SlabRuleType)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SLAB_TYPES.map((rt) => (
                    <SelectItem key={rt} value={rt}>
                      {rt}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>State</Label>
              <Select value={state} onValueChange={setState}>
                <SelectTrigger>
                  <SelectValue placeholder="Pick a state" />
                </SelectTrigger>
                <SelectContent>
                  {stateOptions.map((s) => (
                    <SelectItem key={s} value={s}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label>Add custom state</Label>
              <div className="flex gap-2">
                <Input
                  placeholder="e.g. Tamil Nadu"
                  value={customState}
                  onChange={(e) => setCustomState(e.target.value)}
                />
                <Button type="button" variant="outline" onClick={useCustomState}>
                  Use
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-3">
          <div>
            <CardTitle>
              {ruleType} slabs — {state || "—"}
            </CardTitle>
            <p className="text-xs text-slate-500">
              Slabs must be non-overlapping. Sum of deductions: {sumPreview.toFixed(2)}
            </p>
            <p className="text-xs text-slate-500 mt-1">
              Built-in {ruleType} defaults available for:{" "}
              <span className="text-slate-700">{defaultStates.join(", ") || "—"}</span>
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {defaultStates.includes(state) && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleImportCurrent}
                disabled={importing}
              >
                {importing ? "Importing…" : `Load defaults for ${state}`}
              </Button>
            )}
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={handleImportAll}
              disabled={importing || defaultStates.length === 0}
            >
              Import all {ruleType} defaults
            </Button>
            <Button
              type="button"
              variant="destructive"
              size="sm"
              onClick={handleResetAll}
              disabled={importing || defaultStates.length === 0}
              title={`Wipe and re-seed every ${ruleType} state from the curated catalog`}
            >
              Reset & re-seed {ruleType}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : (
            <SlabTable
              slabs={slabs}
              onChange={setSlabs}
              errors={errors}
              showEmployer={ruleType === "LWF"}
            />
          )}
        </CardContent>
      </Card>

      <div className="flex items-center justify-end gap-2">
        <Button type="button" variant="outline" onClick={loadSlabs} disabled={loading}>
          Reload
        </Button>
        <Button type="button" onClick={handleSave} disabled={saving || !state}>
          {saving ? "Saving…" : "Save Slabs"}
        </Button>
      </div>
    </div>
  );
}
