"use client";

import { useState } from "react";
import { apiFetch, parseEnvelopeResponse } from "@/lib/api";
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

  const download = async () => {
    setError("");
    try {
      const response = await apiFetch("/api/config/bundle/export.csv");
      if (!response.ok) throw new Error(`Download failed (${response.status})`);
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "peopleopslab-configuration.csv";
      anchor.click();
      URL.revokeObjectURL(url);
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
      <PageHeader eyebrow="Settings" title="Configuration upload" description="Download your CSV template, edit the values and mappings, preview the changes, then upload it." />
      {error && <AlertBanner variant="error" title="Upload error">{error}</AlertBanner>}
      {message && <AlertBanner variant="success" title="Saved">{message}</AlertBanner>}
      <Card><CardContent className="space-y-5 py-6">
        <p className="text-sm text-ink-600">The CSV covers salary components, statutory settings, formulas, PT/LWF slabs, minimum-wage rates and applicability, rule choices, salary import mappings, bank profiles and JV mappings. It contains your configuration; keep it private.</p>
        <div className="space-y-2 rounded-lg border p-4 text-sm text-ink-600">
          <p><strong>CSV format:</strong> section, record, field, type, value. Each line sets one field of one record. Lines with the same section and record number belong to one configuration item.</p>
          <p>Keep the column headings and field names. Edit the value column. Types are text, number, boolean (true/false), null, and json for nested mappings. An empty section uses record 0 and type empty.</p>
          <p>A section included in the CSV replaces that entire section for this entity, including an empty section. Remove all lines for a section to leave it unchanged. Download a fresh backup and preview before applying.</p>
        </div>
        <Button type="button" variant="outline" onClick={() => void download()}>Download configuration CSV template</Button>
        <label className="block space-y-2 text-sm font-medium">Choose edited CSV file
          <input type="file" accept=".csv,text/csv" className="block w-full rounded-lg border p-3" onChange={e => { setFile(e.target.files?.[0] ?? null); setPreview(null); }} />
        </label>
        <Button type="button" disabled={!file || busy} onClick={() => void upload(true)}>Preview upload</Button>
        {preview && <div className="space-y-3 rounded-lg border p-4 text-sm">
          <p className="font-semibold">These sections will replace the selected entity’s existing configuration:</p>
          <ul className="list-inside list-disc">{Object.entries(preview).map(([name, count]) => <li key={name}>{name.replaceAll("_", " ")}: {count} row{count === 1 ? "" : "s"}</li>)}</ul>
          <p>Download a backup first. JV imports become drafts and require approval in the JV editor.</p>
          <Button type="button" disabled={busy} onClick={() => void upload(false)}>Apply configuration</Button>
        </div>}
      </CardContent></Card>
      <CopyFromCompany />
    </div>
  );
}

const SECTION_NAMES = [
  "components", "statutory_settings", "statutory_engine", "formulas", "pt_lwf_slabs", "minimum_wage_rates",
  "minimum_wage_applicability", "rule_preferences", "salary_import_profiles", "bank_file_profiles", "jv_templates",
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
      <h2 className="text-base font-semibold text-ink-900 dark:text-white">Copy from another company</h2>
      <p className="text-sm text-ink-600">Bring {entity?.name ?? "this company"} the configuration of a company you already set up. Each section you choose replaces that section here; nothing changes until you have seen the preview. JV templates arrive as drafts.</p>
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
