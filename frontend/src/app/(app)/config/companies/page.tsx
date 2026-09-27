"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Building2, Loader2, Plus, Save, ShieldCheck } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import { useEntity, type Entity } from "@/context/EntityContext";
import { apiFetch, parseEnvelopeResponse } from "@/lib/api";

type CompanyForm = {
  name: string;
  legal_name: string;
  code: string;
  primary_state: string;
  pf_establishment_code: string;
  esic_employer_code: string;
  tan: string;
  pan: string;
  cin: string;
};

const blank: CompanyForm = {
  name: "", legal_name: "", code: "", primary_state: "",
  pf_establishment_code: "", esic_employer_code: "",
  tan: "", pan: "", cin: "",
};

const fields: { key: keyof CompanyForm; label: string; hint?: string }[] = [
  { key: "name", label: "Company name" },
  { key: "legal_name", label: "Registered legal name" },
  { key: "code", label: "Internal company code", hint: "Optional; generated if blank" },
  { key: "primary_state", label: "Primary state" },
  { key: "pan", label: "PAN" },
  { key: "tan", label: "TAN" },
  { key: "cin", label: "CIN" },
  { key: "pf_establishment_code", label: "PF establishment code" },
  { key: "esic_employer_code", label: "ESIC employer code" },
];

function toForm(company: Entity): CompanyForm {
  return {
    name: company.name,
    legal_name: company.legal_name ?? "",
    code: company.code,
    primary_state: company.primary_state ?? "",
    pf_establishment_code: company.pf_establishment_code ?? "",
    esic_employer_code: company.esic_employer_code ?? "",
    tan: company.tan ?? "",
    pan: company.pan ?? "",
    cin: company.cin ?? "",
  };
}

async function saveCompany(form: CompanyForm, id?: string): Promise<Entity> {
  const body = Object.fromEntries(
    Object.entries(form)
      .filter(([key]) => !id || key !== "code")
      .map(([key, value]) => [key, value.trim() || null]),
  );
  if (!id && !body.code) delete body.code;
  const res = await apiFetch(id ? `/api/org/entities/${id}` : "/api/org/entities", {
    method: id ? "PATCH" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseEnvelopeResponse<Entity>(res);
}

export default function CompanySettingsPage() {
  const { organization, role, entity, entities, loading, reload, switchEntity } = useEntity();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [form, setForm] = useState<CompanyForm>(blank);
  const [message, setMessage] = useState<string | null>(null);
  const [opening, setOpening] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () => saveCompany(form, editing === "new" ? undefined : editing ?? undefined),
    onSuccess: async (company) => {
      await reload();
      await queryClient.invalidateQueries({ queryKey: ["org", "portfolio"] });
      await queryClient.invalidateQueries({ queryKey: ["org-context"] });
      setEditing(null);
      setForm(blank);
      setMessage(`${company.name} saved. Configure its statutory rules before uploading payroll.`);
    },
  });

  const mayManage = role === "owner" || role === "manager";
  const inputClass = "mt-1 w-full rounded-lg border border-ink-200 bg-white px-3 py-2 text-sm text-ink-900 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20";

  function start(company?: Entity) {
    save.reset();
    setMessage(null);
    setEditing(company?.id ?? "new");
    setForm(company ? toForm(company) : blank);
  }

  async function open(company: Entity) {
    setOpening(company.id);
    setMessage(null);
    try {
      await switchEntity(company.id);
      await queryClient.invalidateQueries();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not switch company.");
    } finally {
      setOpening(null);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Group companies"
        description={`Manage the legal employers inside ${organization?.name ?? "this workspace"}. Each company&apos;s registers, components and validation settings stay separate.`}
      />

      {message && <AlertBanner variant="info" title="Company setup">{message}</AlertBanner>}
      {save.isError && (
        <AlertBanner variant="error" title="Could not save company">
          {save.error instanceof Error ? save.error.message : "Please review the details and try again."}
        </AlertBanner>
      )}

      <div className="grid gap-4 md:grid-cols-[1fr_auto] md:items-center">
        <div className="flex items-start gap-3 rounded-xl border border-brand-200 bg-brand-50 p-4 text-sm text-ink-700">
          <ShieldCheck size={18} className="mt-0.5 shrink-0 text-brand-700" aria-hidden />
          <p>Invite HR users from <Link href="/config/team" className="font-semibold text-brand-700 underline">Team &amp; invitations</Link> and select the companies they can access. A role applies to all companies assigned to that user. Group owners should review access before sharing an invitation.</p>
        </div>
        {mayManage && (
          <button type="button" onClick={() => start()} className="inline-flex items-center justify-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700">
            <Plus size={16} aria-hidden /> Add company
          </button>
        )}
      </div>

      {editing && mayManage && (
        <Card>
          <CardContent className="space-y-4 py-5">
            <div>
              <h2 className="text-base font-semibold text-ink-900">{editing === "new" ? "Add legal employer" : "Edit company details"}</h2>
              <p className="mt-1 text-xs text-ink-500">Use the identifiers shown on this company&apos;s registrations. State rules and salary components are configured after creation.</p>
            </div>
            <form onSubmit={(event) => { event.preventDefault(); if (!save.isPending) save.mutate(); }} className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {fields.filter((field) => editing === "new" || field.key !== "code").map((field) => (
                  <label key={field.key} className="block text-xs font-semibold text-ink-700">
                    {field.label}{field.key === "name" ? " *" : ""}
                    <input
                      value={form[field.key]}
                      onChange={(event) => setForm((current) => ({ ...current, [field.key]: event.target.value }))}
                      required={field.key === "name"}
                      maxLength={field.key === "name" || field.key === "legal_name" ? 255 : field.key === "primary_state" ? 100 : field.key === "cin" ? 32 : field.key === "pan" || field.key === "tan" ? 16 : 64}
                      className={inputClass}
                    />
                    {field.hint && <span className="mt-1 block font-normal text-ink-500">{field.hint}</span>}
                  </label>
                ))}
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="submit" disabled={save.isPending || !form.name.trim()} className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
                  {save.isPending ? <Loader2 size={15} className="animate-spin" aria-hidden /> : <Save size={15} aria-hidden />} Save company
                </button>
                <button type="button" onClick={() => { setEditing(null); save.reset(); }} className="rounded-lg border border-ink-200 px-4 py-2 text-sm font-medium text-ink-700">Cancel</button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {loading ? <p className="text-sm text-ink-500">Loading companies…</p> : entities.length === 0 ? (
        <Card><CardContent className="py-8 text-center text-sm text-ink-500">No companies are available to this account.</CardContent></Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {entities.map((company) => (
            <Card key={company.id}>
              <CardContent className="space-y-4 py-5">
                <div className="flex items-start gap-3">
                  <div className="rounded-xl bg-brand-50 p-2.5 text-brand-700"><Building2 size={18} aria-hidden /></div>
                  <div className="min-w-0">
                    <h2 className="font-semibold text-ink-900">{company.name}</h2>
                    <p className="text-xs text-ink-500">{company.code} · {company.primary_state || "State not set"}</p>
                    {company.legal_name && company.legal_name !== company.name && <p className="mt-1 text-xs text-ink-600">{company.legal_name}</p>}
                  </div>
                </div>
                <p className="text-xs text-ink-500">
                  {[
                    company.pan && "PAN",
                    company.tan && "TAN",
                    company.pf_establishment_code && "PF",
                    company.esic_employer_code && "ESIC",
                  ].filter(Boolean).join(" · ") || "Registration identifiers still need review"}
                </p>
                <div className="flex flex-wrap gap-2 border-t border-ink-100 pt-3">
                  <button type="button" disabled={opening === company.id} onClick={() => void open(company)} className="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">
                    {opening === company.id ? <Loader2 size={13} className="animate-spin" aria-hidden /> : <ArrowRight size={13} aria-hidden />} Select company
                  </button>
                  {mayManage && <button type="button" onClick={() => start(company)} className="rounded-lg border border-ink-200 px-3 py-1.5 text-xs font-semibold text-ink-700">Edit details</button>}
                  {entity?.id === company.id && <Link href="/config/statutory" className="rounded-lg border border-ink-200 px-3 py-1.5 text-xs font-semibold text-ink-700">Statutory setup</Link>}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
