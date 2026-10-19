"use client";

import { useState } from "react";
import { apiBlob, apiFetch, parseEnvelopeResponse } from "@/lib/api";
import { saveBlob } from "@/lib/download";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { AlertBanner } from "@/components/ui/alert-banner";
import { useEntity } from "@/context/EntityContext";

type Result = { preview: boolean; replace_sections?: Record<string, number>; replaced_sections?: Record<string, number> };

export default function ConfigurationUploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Record<string, number> | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const download = async (ext: "csv" | "xlsx") => {
    setError("");
    try {
      saveBlob(await apiBlob(`/api/config/bundle/export.${ext}`), `configuration.${ext}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not download configuration");
    }
  };

  const upload = async (dryRun: boolean) => {
    if (!file) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await apiFetch(`/api/config/bundle/import?dry_run=${dryRun}`, { method: "POST", body: form });
      const result = await parseEnvelopeResponse<Result>(response);
      if (dryRun) setPreview(result.replace_sections ?? {});
      else {
        setMessage("Configuration uploaded. Review each section before running payroll validation.");
        setPreview(null);
        setFile(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Configuration upload failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-8">
      <PageHeader eyebrow="Settings" title="Configuration upload" description="Set up or change many settings in one spreadsheet: download it, edit it, preview, then upload." />
      {error && <AlertBanner variant="error" title="Upload error">{error}</AlertBanner>}
      {message && <AlertBanner variant="success" title="Saved">{message}</AlertBanner>}
      <Card><CardContent className="space-y-5 py-6">
        <div className="space-y-2 rounded-lg border p-4 text-sm text-ink-600">
          <p><strong>What is in it:</strong> salary components, PF / ESIC / PT / LWF settings and formulas, PT and LWF slabs, minimum-wage decision and rates, switched-off checks, and import column mappings. It holds your configuration; keep it private.</p>
          <p><strong>Excel:</strong> one sheet per kind of setting; empty sheets are left alone. <strong>CSV:</strong> the same tables in one file as section, record, field and value lines.</p>
          <p>Use Yes or No for switches, YYYY-MM-DD for dates and commas between list items. A kind of setting is applied when it has at least one filled row, and replaces what is there. Preview before you apply.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold text-ink-500">Download current configuration (also the template)</span>
          <Button type="button" variant="outline" onClick={() => void download("csv")}>CSV</Button>
          <Button type="button" variant="outline" onClick={() => void download("xlsx")}>Excel</Button>
        </div>
        <label className="block space-y-2 text-sm font-medium">Choose the edited file (.csv or .xlsx)
          <input type="file" accept=".csv,.xlsx" className="block w-full rounded-lg border p-3" onChange={e => { setFile(e.target.files?.[0] ?? null); setPreview(null); }} />
        </label>
        <Button type="button" disabled={!file || busy} onClick={() => void upload(true)}>Preview upload</Button>
        {preview && <div className="space-y-3 rounded-lg border p-4 text-sm">
          <p className="font-semibold">These will replace the existing settings of the selected company:</p>
          <ul className="list-inside list-disc">{Object.entries(preview).map(([name, count]) => <li key={name}>{LABELS[name] ?? name.replaceAll("_", " ")}: {count} row{count === 1 ? "" : "s"}</li>)}</ul>
          <Button type="button" disabled={busy} onClick={() => void upload(false)}>Apply configuration</Button>
        </div>}
      </CardContent></Card>
      <CopyFromCompany />
    </div>
  );
}

const LABELS: Record<string, string> = {
  components: "salary components", statutory_settings: "PT and LWF states and PF / ESIC amounts",
  statutory_engine: "PF and ESIC calculation", pt_lwf_slabs: "PT / LWF slabs",
  minimum_wage_rates: "minimum wage rates", minimum_wage_applicability: "minimum wage decision",
  rule_preferences: "switched-off checks", salary_import_profiles: "import column mappings",
};

const SECTION_NAMES = [
  "components", "statutory_settings", "statutory_engine", "pt_lwf_slabs", "minimum_wage_rates",
  "minimum_wage_applicability", "rule_preferences", "salary_import_profiles",
];
type CopyPlan = { preview: boolean; source: { id: string; name: string }; sections: Record<string, { from_source: number; replacing_here: number }> };

/**
 * Copy configuration from another company in the group, without a file in
 * between: the same sections, checked the same way, previewed first, and
 * recorded in both companies' audit trails.
 */
function CopyFromCompany() {
  const { entity, entities } = useEntity();
  const others = entities.filter((e) => e.id !== entity?.id);
  const [source, setSource] = useState("");
  const [sections, setSections] = useState<string[]>(["components"]);
  const [reason, setReason] = useState("");
  const [plan, setPlan] = useState<CopyPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  if (!others.length) return null;

  const run = async (dryRun: boolean) => {
    setBusy(true); setError(""); setDone("");
    try {
      const response = await apiFetch("/api/config/bundle/copy", {
        method: "POST",
        body: JSON.stringify({ source_entity_id: source, sections, reason, dry_run: dryRun }),
      });
      const result = await parseEnvelopeResponse<CopyPlan>(response);
      if (dryRun) setPlan(result);
      else { setPlan(null); setDone(`Copied from ${result.source.name}. Review each section before validating.`); }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Copy failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card><CardContent className="space-y-4 py-6">
      <h2 className="text-base font-semibold text-ink-900">Copy from another company</h2>
      <p className="text-sm text-ink-600">Bring {entity?.name ?? "this company"} the configuration of a company you already set up. Each section you choose replaces that section here; nothing changes until you have seen the preview.</p>
      {error && <AlertBanner variant="error" title="Not copied">{error}</AlertBanner>}
      {done && <AlertBanner variant="success" title="Copied">{done}</AlertBanner>}
      <label className="block max-w-sm text-sm font-medium">From
        <select className="mt-1 block w-full rounded-lg border p-2 text-sm" value={source} onChange={(e) => { setSource(e.target.value); setPlan(null); }}>
          <option value="">Choose a company</option>
          {others.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
        </select>
      </label>
      <fieldset className="flex flex-wrap gap-3 text-sm">
        <legend className="mb-1 font-medium">Sections</legend>
        {SECTION_NAMES.map((name) => (
          <label key={name} className="flex items-center gap-1.5">
            <input type="checkbox" checked={sections.includes(name)} onChange={(e) => { setPlan(null); setSections(e.target.checked ? [...sections, name] : sections.filter((x) => x !== name)); }} />
            {name.replaceAll("_", " ")}
          </label>
        ))}
      </fieldset>
      <input aria-label="Reason for copying" className="block w-full rounded-lg border p-2 text-sm" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why (kept in both companies' audit trails)" />
      <Button type="button" disabled={busy || !source || !sections.length || reason.trim().length < 8} onClick={() => void run(true)}>Preview copy</Button>
      {plan && <div className="space-y-3 rounded-lg border p-4 text-sm">
        <p className="font-semibold">From {plan.source.name}:</p>
        <ul className="list-inside list-disc">{Object.entries(plan.sections).map(([name, c]) => <li key={name}>{name.replaceAll("_", " ")}: {c.from_source} row(s) replacing {c.replacing_here} here</li>)}</ul>
        <Button type="button" disabled={busy} onClick={() => void run(false)}>Copy these sections</Button>
      </div>}
    </CardContent></Card>
  );
}
