"use client";

import { apiJson } from "@/lib/api";
import { useCallback, useEffect, useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Badge } from "@/components/ui/badge";
import { Plus, Pencil, Trash2 } from "lucide-react";

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

const emptyForm: Omit<ComponentRow, "id"> = {
  component_name: "",
  pf_applicable: false,
  esic_applicable: false,
  pt_applicable: false,
  lwf_applicable: false,
  bonus_applicable: false,
  included_in_wages: false,
  taxable: false,
  tax_exemption_type: "none",
};

export default function ComponentsPage() {
  const [rows, setRows] = useState<ComponentRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<ComponentRow | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiJson<ComponentRow[]>("/api/components");
      setRows(data);
      setError(null);
    } catch {
      setError("Failed to load components");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    setEditing(null);
    setForm(emptyForm);
  };

  const openEdit = (r: ComponentRow) => {
    setEditing(r);
    setForm({
      component_name: r.component_name,
      pf_applicable: r.pf_applicable,
      esic_applicable: r.esic_applicable,
      pt_applicable: r.pt_applicable,
      lwf_applicable: r.lwf_applicable,
      bonus_applicable: r.bonus_applicable,
      included_in_wages: r.included_in_wages,
      taxable: r.taxable,
      tax_exemption_type: r.tax_exemption_type,
    });
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      if (editing) {
        await apiJson(`/api/components/${editing.id}`, {
          method: "PATCH",
          body: JSON.stringify(form),
        });
      } else {
        await apiJson("/api/components", {
          method: "POST",
          body: JSON.stringify(form),
        });
      }
      setEditing(null);
      setForm(emptyForm);
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    if (!confirm("Delete this component?")) return;
    try {
      await apiJson(`/api/components/${id}`, { method: "DELETE" });
    } catch {
      setError("Delete failed");
      return;
    }
    await load();
  };

  const yesNo = (v: boolean) =>
    v ? (
      <Badge variant="success">Yes</Badge>
    ) : (
      <span className="text-xs text-ink-400 dark:text-ink-500">No</span>
    );

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Library"
        title="Salary components"
        description="Map statutory flags once; uploads must include columns matching these names."
        actions={
          <Button type="button" onClick={openCreate}>
            <Plus size={15} strokeWidth={2.25} /> Add component
          </Button>
        }
      />

      {error && (
        <AlertBanner variant="error" title="Save failed">
          {error}
        </AlertBanner>
      )}

      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="bg-ink-50/80 text-left text-[11px] font-bold uppercase tracking-[0.12em] text-ink-500 dark:bg-white/[0.03] dark:text-ink-300">
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">PF</th>
                <th className="px-4 py-3">ESIC</th>
                <th className="px-4 py-3">PT</th>
                <th className="px-4 py-3">LWF</th>
                <th className="px-4 py-3">Bonus</th>
                <th className="px-4 py-3">Wages</th>
                <th className="px-4 py-3">Tax</th>
                <th className="px-4 py-3">Exemption</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100 dark:divide-white/[0.05]">
              {loading ? (
                <tr>
                  <td colSpan={10} className="px-4 py-12 text-center text-ink-500 dark:text-ink-400">
                    Loading…
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={10} className="px-4 py-12 text-center text-ink-500 dark:text-ink-400">
                    No components yet — start with{" "}
                    <button
                      type="button"
                      onClick={openCreate}
                      className="font-semibold text-brand-700 hover:text-brand-800 dark:text-brand-300"
                    >
                      add component
                    </button>
                    .
                  </td>
                </tr>
              ) : (
                rows.map((r) => (
                  <tr
                    key={r.id}
                    className="transition-colors hover:bg-ink-50/60 dark:hover:bg-white/[0.04]"
                  >
                    <td className="px-4 py-3 font-semibold text-ink-900 dark:text-white">
                      {r.component_name}
                    </td>
                    <td className="px-4 py-3">{yesNo(r.pf_applicable)}</td>
                    <td className="px-4 py-3">{yesNo(r.esic_applicable)}</td>
                    <td className="px-4 py-3">{yesNo(r.pt_applicable)}</td>
                    <td className="px-4 py-3">{yesNo(r.lwf_applicable)}</td>
                    <td className="px-4 py-3">{yesNo(r.bonus_applicable)}</td>
                    <td className="px-4 py-3">{yesNo(r.included_in_wages)}</td>
                    <td className="px-4 py-3">{yesNo(r.taxable)}</td>
                    <td className="px-4 py-3 text-xs text-ink-500 dark:text-ink-400">
                      {r.tax_exemption_type}
                    </td>
                    <td className="space-x-3 whitespace-nowrap px-4 py-3 text-right">
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 text-xs font-semibold text-brand-700 transition-colors hover:text-brand-800 dark:text-brand-300 dark:hover:text-brand-200"
                        onClick={() => openEdit(r)}
                      >
                        <Pencil size={12} /> Edit
                      </button>
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 text-xs font-semibold text-danger-600 transition-colors hover:text-danger-700 dark:text-danger-400 dark:hover:text-danger-300"
                        onClick={() => void remove(r.id)}
                      >
                        <Trash2 size={12} /> Delete
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <CardContent className="space-y-5 p-6">
          <h2 className="font-display text-lg font-bold tracking-tight text-ink-900 dark:text-white">
            {editing ? "Edit component" : "New component"}
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Component name">
              <input
                className="mt-1.5 w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900 shadow-sm transition-colors focus:outline-none focus:ring-2 focus:ring-brand-500/40 dark:border-white/10 dark:bg-white/[0.04] dark:text-white"
                value={form.component_name}
                onChange={(e) => setForm({ ...form, component_name: e.target.value })}
              />
            </Field>
            <Field label="Tax exemption type">
              <input
                className="mt-1.5 w-full rounded-xl border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900 shadow-sm transition-colors placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-brand-500/40 dark:border-white/10 dark:bg-white/[0.04] dark:text-white dark:placeholder:text-ink-500"
                value={form.tax_exemption_type}
                onChange={(e) => setForm({ ...form, tax_exemption_type: e.target.value })}
                placeholder="none, HRA, LTA…"
              />
            </Field>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Toggle
              label="PF applicable"
              checked={form.pf_applicable}
              onChange={(v) => setForm({ ...form, pf_applicable: v })}
            />
            <Toggle
              label="ESIC applicable"
              checked={form.esic_applicable}
              onChange={(v) => setForm({ ...form, esic_applicable: v })}
            />
            <Toggle
              label="PT applicable"
              checked={form.pt_applicable}
              onChange={(v) => setForm({ ...form, pt_applicable: v })}
            />
            <Toggle
              label="LWF applicable"
              checked={form.lwf_applicable}
              onChange={(v) => setForm({ ...form, lwf_applicable: v })}
            />
            <Toggle
              label="Bonus applicable"
              checked={form.bonus_applicable}
              onChange={(v) => setForm({ ...form, bonus_applicable: v })}
            />
            <Toggle
              label="Included in wages"
              checked={form.included_in_wages}
              onChange={(v) => setForm({ ...form, included_in_wages: v })}
            />
            <Toggle
              label="Taxable"
              checked={form.taxable}
              onChange={(v) => setForm({ ...form, taxable: v })}
            />
          </div>
          <Button
            type="button"
            disabled={saving || !form.component_name.trim()}
            onClick={() => void save()}
          >
            {saving ? "Saving…" : "Save"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="font-display text-[11px] font-bold uppercase tracking-[0.12em] text-ink-600 dark:text-ink-300">
        {label}
      </span>
      {children}
    </label>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-ink-200/70 bg-ink-50/40 px-3 py-2 text-sm font-medium text-ink-800 transition-colors hover:bg-ink-100/60 dark:border-white/10 dark:bg-white/[0.03] dark:text-ink-200 dark:hover:bg-white/[0.07]">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="accent-brand-600"
      />
      {label}
    </label>
  );
}
