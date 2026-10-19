"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Plus, Search, Trash2 } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { apiJson } from "@/lib/api";
import { cn } from "@/lib/utils";

type ComponentRow = {
  id: string;
  component_name: string;
  pf_applicable: boolean;
  esic_applicable: boolean;
  pt_applicable: boolean;
  lwf_applicable: boolean;
  bonus_applicable: boolean;
  included_in_wages: boolean;
  taxable: boolean;
  tax_exemption_type: string;
};
type Form = Omit<ComponentRow, "id">;

const EMPTY: Form = {
  component_name: "",
  pf_applicable: false,
  esic_applicable: false,
  pt_applicable: false,
  lwf_applicable: false,
  bonus_applicable: false,
  included_in_wages: true,
  taxable: true,
  tax_exemption_type: "none",
};

const FLAGS: { key: keyof Form; label: string; hint: string; chip?: string }[] = [
  { key: "pf_applicable", label: "Affects PF", hint: "Counts toward the PF wage", chip: "PF" },
  { key: "esic_applicable", label: "Affects ESIC", hint: "Counts toward the ESIC wage", chip: "ESIC" },
  { key: "pt_applicable", label: "Affects PT gross", hint: "Counts toward professional-tax gross", chip: "PT" },
  { key: "lwf_applicable", label: "Affects LWF", hint: "Counts toward labour welfare fund wage", chip: "LWF" },
  { key: "bonus_applicable", label: "Affects bonus", hint: "Counts toward the bonus wage", chip: "Bonus" },
  { key: "included_in_wages", label: "Counts as wages", hint: "Part of wages under the labour codes" },
  { key: "taxable", label: "Taxable", hint: "Part of taxable income" },
];

/** The name a formula and an import column use for this component. */
const variableName = (name: string) =>
  name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/_+/g, "_").replace(/^_|_$/g, "");

const toForm = (r: ComponentRow): Form => {
  const { id: _id, ...rest } = r;
  return rest;
};

/**
 * Salary components: a list on the left, one component on the right. Only what
 * validation needs is asked — the name, and which statutory wages it feeds.
 */
export default function ComponentsPage() {
  const [rows, setRows] = useState<ComponentRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | "new">("new");
  const [form, setForm] = useState<Form>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [query, setQuery] = useState("");

  const load = useCallback(async (keep?: string) => {
    setLoading(true);
    try {
      const data = await apiJson<ComponentRow[]>("/api/components");
      setRows(data);
      setError(null);
      const target = keep ? data.find((r) => r.id === keep) : undefined;
      if (target) {
        setSelected(target.id);
        setForm(toForm(target));
      } else if (!keep && data.length) {
        setSelected(data[0].id);
        setForm(toForm(data[0]));
      }
    } catch {
      setError("The components could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const current = rows.find((r) => r.id === selected);
  const dirty = useMemo(
    () => (current ? JSON.stringify(toForm(current)) !== JSON.stringify(form) : JSON.stringify(EMPTY) !== JSON.stringify(form)),
    [current, form],
  );
  const shown = rows.filter((r) => r.component_name.toLowerCase().includes(query.trim().toLowerCase()));

  const choose = (r: ComponentRow) => {
    if (dirty && !confirm("Discard your unsaved changes?")) return;
    setSelected(r.id);
    setForm(toForm(r));
    setError(null);
  };

  const startNew = () => {
    if (dirty && !confirm("Discard your unsaved changes?")) return;
    setSelected("new");
    setForm(EMPTY);
    setError(null);
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      if (current) {
        await apiJson(`/api/components/${current.id}`, { method: "PATCH", body: JSON.stringify(form) });
        await load(current.id);
      } else {
        const created = await apiJson<ComponentRow>("/api/components", { method: "POST", body: JSON.stringify(form) });
        await load(created.id);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!current || !confirm(`Delete “${current.component_name}”? Formulas and imports that use it will stop finding it.`)) return;
    try {
      await apiJson(`/api/components/${current.id}`, { method: "DELETE" });
    } catch {
      setError("Delete failed");
      return;
    }
    setSelected("new");
    setForm(EMPTY);
    await load();
  };

  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => ({ ...f, [key]: value }));

  return (
    <div className="space-y-4">
      <PageHeader
        title="Salary components"
        description="The earnings and deductions on your payslip, and which statutory wages each one feeds. They become columns in the salary register and CTC templates and names you can use in formulas."
      />

      {error ? <AlertBanner variant="error" title="Not saved">{error}</AlertBanner> : null}

      <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        <section className="flex max-h-[calc(100vh-14rem)] min-h-[360px] flex-col rounded-xl border border-ink-200 bg-white shadow-soft">
          <div className="border-b border-ink-100 p-3">
            <label className="relative block">
              <Search size={14} aria-hidden className="pointer-events-none absolute left-2.5 top-2.5 text-ink-400" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search components"
                aria-label="Search components"
                className="h-9 w-full rounded-lg border border-ink-200 pl-8 pr-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-brand-500/20"
              />
            </label>
          </div>
          <ul className="scrollbar-thin flex-1 space-y-1.5 overflow-y-auto p-2.5">
            {loading ? <li className="p-4 text-center text-sm text-ink-500">Loading…</li> : null}
            {!loading && rows.length === 0 ? (
              <li className="p-4 text-center text-sm text-ink-500">No components yet. Fill in the form and choose Add component.</li>
            ) : null}
            {shown.map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  onClick={() => choose(r)}
                  aria-current={selected === r.id}
                  className={cn(
                    "w-full rounded-lg border px-3 py-2 text-left transition-colors",
                    selected === r.id ? "border-brand-300 bg-brand-50" : "border-ink-200 hover:bg-ink-50",
                  )}
                >
                  <span className="block truncate text-[14px] font-medium text-ink-900">{r.component_name}</span>
                  <span className="mt-0.5 flex items-center gap-1.5 text-[11px] text-ink-500">
                    <span className="truncate font-mono">{variableName(r.component_name)}</span>
                    {FLAGS.filter((f) => f.chip && r[f.key as keyof ComponentRow]).map((f) => (
                      <span key={f.chip} className="rounded bg-ink-100 px-1.5 py-px font-medium text-ink-600">{f.chip}</span>
                    ))}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <div className="border-t border-ink-100 p-2.5">
            <Button type="button" variant="outline" className="w-full" onClick={startNew}>
              <Plus size={14} /> Add new component
            </Button>
          </div>
        </section>

        <section className="rounded-xl border border-ink-200 bg-white shadow-soft">
          <header className="flex flex-wrap items-center justify-between gap-2 border-b border-ink-100 px-5 py-3">
            <h2 className="text-[15px] font-semibold text-ink-900">
              {current ? current.component_name : "New component"}
              {dirty ? <span className="ml-2 text-xs font-normal text-warning-700">unsaved changes</span> : null}
            </h2>
            <div className="flex items-center gap-2">
              {current ? (
                <Button type="button" variant="outline" onClick={() => void remove()}>
                  <Trash2 size={14} /> Delete
                </Button>
              ) : null}
              <Button type="button" disabled={saving || !form.component_name.trim() || !dirty} onClick={() => void save()}>
                {saving ? "Saving…" : current ? "Save changes" : "Add component"}
              </Button>
            </div>
          </header>

          <div className="space-y-5 p-5">
            <div>
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-500">General</p>
              <div className="grid gap-3 sm:grid-cols-3">
                <label className="block text-[13px] font-medium text-ink-800">
                  Component name
                  <input
                    value={form.component_name}
                    onChange={(e) => set("component_name", e.target.value)}
                    maxLength={100}
                    placeholder="e.g. Special Allowance"
                    className="mt-1 h-9 w-full rounded-lg border border-ink-200 px-3 text-[13px] font-normal focus:outline-none focus:ring-2 focus:ring-brand-500/20"
                  />
                </label>
                <label className="block text-[13px] font-medium text-ink-800">
                  Used in formulas as
                  <input
                    value={variableName(form.component_name)}
                    readOnly
                    aria-label="Variable name"
                    className="mt-1 h-9 w-full rounded-lg border border-ink-200 bg-ink-50 px-3 font-mono text-[13px] font-normal text-ink-600"
                  />
                </label>
                <label className="block text-[13px] font-medium text-ink-800">
                  Tax exemption
                  <input
                    value={form.tax_exemption_type}
                    onChange={(e) => set("tax_exemption_type", e.target.value)}
                    list="exemption-types"
                    maxLength={20}
                    className="mt-1 h-9 w-full rounded-lg border border-ink-200 px-3 text-[13px] font-normal focus:outline-none focus:ring-2 focus:ring-brand-500/20"
                  />
                  <datalist id="exemption-types">
                    {["none", "HRA", "LTA", "Conveyance", "Medical", "Other"].map((o) => <option key={o} value={o} />)}
                  </datalist>
                </label>
              </div>
            </div>

            <div>
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-500">Statutory</p>
              <div className="grid gap-x-6 gap-y-2.5 sm:grid-cols-2">
                {FLAGS.map((f) => (
                  <label key={f.key} className="flex cursor-pointer items-start gap-2.5 text-[13px]">
                    <input
                      type="checkbox"
                      checked={form[f.key] as boolean}
                      onChange={(e) => set(f.key, e.target.checked as never)}
                      className="mt-0.5 h-4 w-4 accent-brand-600"
                    />
                    <span>
                      <span className="block font-medium text-ink-900">{f.label}</span>
                      <span className="block text-xs text-ink-500">{f.hint}</span>
                    </span>
                  </label>
                ))}
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
