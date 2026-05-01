"use client";

import { apiJson } from "@/lib/api";
import { useCallback, useEffect, useState } from "react";

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

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Salary components</h1>
          <p className="text-sm text-slate-600 mt-1">
            Map statutory flags once; uploads must include columns matching these names.
          </p>
        </div>
        <button
          type="button"
          onClick={openCreate}
          className="self-start rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          Add component
        </button>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="rounded-lg border border-slate-200 bg-white overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2">PF</th>
              <th className="px-3 py-2">ESIC</th>
              <th className="px-3 py-2">PT</th>
              <th className="px-3 py-2">LWF</th>
              <th className="px-3 py-2">Bonus</th>
              <th className="px-3 py-2">Wages</th>
              <th className="px-3 py-2">Tax</th>
              <th className="px-3 py-2">Exemption</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={10} className="px-3 py-6 text-center text-slate-500">
                  Loading…
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={r.id} className="border-t border-slate-100">
                  <td className="px-3 py-2 font-medium text-slate-900">{r.component_name}</td>
                  <td className="px-3 py-2">{r.pf_applicable ? "Yes" : "No"}</td>
                  <td className="px-3 py-2">{r.esic_applicable ? "Yes" : "No"}</td>
                  <td className="px-3 py-2">{r.pt_applicable ? "Yes" : "No"}</td>
                  <td className="px-3 py-2">{r.lwf_applicable ? "Yes" : "No"}</td>
                  <td className="px-3 py-2">{r.bonus_applicable ? "Yes" : "No"}</td>
                  <td className="px-3 py-2">{r.included_in_wages ? "Yes" : "No"}</td>
                  <td className="px-3 py-2">{r.taxable ? "Yes" : "No"}</td>
                  <td className="px-3 py-2">{r.tax_exemption_type}</td>
                  <td className="px-3 py-2 space-x-2 whitespace-nowrap">
                    <button type="button" className="text-brand-700 hover:underline" onClick={() => openEdit(r)}>
                      Edit
                    </button>
                    <button type="button" className="text-red-600 hover:underline" onClick={() => void remove(r.id)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-5 space-y-4">
        <h2 className="text-lg font-medium text-slate-900">{editing ? "Edit component" : "New component"}</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Component name">
            <input
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              value={form.component_name}
              onChange={(e) => setForm({ ...form, component_name: e.target.value })}
            />
          </Field>
          <Field label="Tax exemption type">
            <input
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              value={form.tax_exemption_type}
              onChange={(e) => setForm({ ...form, tax_exemption_type: e.target.value })}
              placeholder="none, HRA, LTA…"
            />
          </Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Toggle label="PF applicable" checked={form.pf_applicable} onChange={(v) => setForm({ ...form, pf_applicable: v })} />
          <Toggle label="ESIC applicable" checked={form.esic_applicable} onChange={(v) => setForm({ ...form, esic_applicable: v })} />
          <Toggle label="PT applicable" checked={form.pt_applicable} onChange={(v) => setForm({ ...form, pt_applicable: v })} />
          <Toggle label="LWF applicable" checked={form.lwf_applicable} onChange={(v) => setForm({ ...form, lwf_applicable: v })} />
          <Toggle label="Bonus applicable" checked={form.bonus_applicable} onChange={(v) => setForm({ ...form, bonus_applicable: v })} />
          <Toggle label="Included in wages" checked={form.included_in_wages} onChange={(v) => setForm({ ...form, included_in_wages: v })} />
          <Toggle label="Taxable" checked={form.taxable} onChange={(v) => setForm({ ...form, taxable: v })} />
        </div>
        <button
          type="button"
          disabled={saving || !form.component_name.trim()}
          onClick={() => void save()}
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-sm text-slate-700">
      <span className="font-medium">{label}</span>
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
    <label className="flex items-center gap-2 text-sm text-slate-800">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}
