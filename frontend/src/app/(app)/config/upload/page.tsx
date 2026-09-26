"use client";

import { useState } from "react";
import { apiFetch, parseEnvelopeResponse } from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { AlertBanner } from "@/components/ui/alert-banner";

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
    </div>
  );
}
