"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";

import { useEntity } from "@/context/EntityContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { StudioNav } from "@/components/studio/StudioNav";
import { integrationBaseUrl } from "@/lib/studio";

const TEMPLATE = "/studio_client_import.py";

export default function PythonIntegrationPage() {
  const { entity } = useEntity();
  const [original, setOriginal] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    fetch(TEMPLATE).then((res) => {
      if (!res.ok) throw new Error("Template download failed (HTTP " + res.status + ")");
      return res.text();
    }).then((text) => {
      if (active) { setOriginal(text); setCode(text); }
    }).catch((e) => { if (active) setError(e instanceof Error ? e.message : "Template unavailable"); });
    return () => { active = false; };
  }, []);

  const download = () => {
    const url = URL.createObjectURL(new Blob([code], { type: "text/x-python;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "studio_client_import.py";
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(code); toast.success("Python copied"); }
    catch { toast.error("Clipboard unavailable; select and copy the editor text"); }
  };
  const base = integrationBaseUrl("/api/integration/v1");

  return (
    <div className="space-y-5">
      <PageHeader title="Client Python integration" description="Adapt a Python importer for a client's own system. Check the records first, then explicitly submit them through Studio's company-scoped API." />
      <StudioNav />
      <AlertBanner variant="info" title={entity ? "Selected company: " + entity.name : "Select a company"}>
        {entity ? <>Company ID: <code className="break-all">{entity.id}</code>. Create a dedicated service account and API key for this company in the <Link className="underline" href="/studio/api">API Centre</Link>.</> : "Choose the company in the application header before configuring a client integration."}
      </AlertBanner>
      <Card><CardContent className="space-y-4 py-5">
        <div>
          <h2 className="text-base font-semibold text-ink-900">Edit and download the starter script</h2>
          <p className="text-sm text-ink-600">Edit <code>transform(row)</code> to map your source columns. You can also publish a Studio mapping and set <code>POL_MAPPING_KEY</code>. The editor is local to this page; download your changes before leaving. No Python is executed in your browser or on our shared application server.</p>
        </div>
        {error ? <AlertBanner variant="error" title="Template unavailable">{error}</AlertBanner> : null}
        <textarea aria-label="Client Python source" spellCheck={false} className="h-[28rem] w-full rounded-lg border border-ink-200 bg-ink-950 p-4 font-mono text-xs leading-relaxed text-ink-100" value={code} onChange={(e) => setCode(e.target.value)} disabled={!original} />
        <div className="flex flex-wrap gap-2">
          <Button onClick={download} disabled={!code}>Download .py</Button>
          <Button variant="outline" onClick={() => void copy()} disabled={!code}>Copy code</Button>
          <Button variant="outline" onClick={() => setCode(original)} disabled={!original || code === original}>Reset template</Button>
        </div>
      </CardContent></Card>
      <Card><CardContent className="space-y-3 py-5 text-sm text-ink-700">
        <h2 className="text-base font-semibold text-ink-900">Run from your controlled environment</h2>
        <ol className="list-decimal space-y-2 pl-5">
          <li>Prepare a JSON array of source records and edit <code>transform(row)</code>. Keep employee IDs as text.</li>
          <li>Set <code>POL_API_KEY</code> in your secret store, plus <code>POL_COMPANY_ID</code>, <code>POL_INPUT_JSON</code>, <code>POL_OBJECT_TYPE</code> and <code>POL_PERIOD</code> (YYYY-MM-01). Never paste a key into this editor.</li>
          <li>Run <code>python studio_client_import.py</code>. It calls the import check and prints counts and rejections without storing data.</li>
          <li>After reviewing totals, run <code>python studio_client_import.py --send</code>. It checks again, sends with an idempotency key, and prints the asynchronous run ID. Open <Link className="text-brand-700 underline" href="/studio/runs">Run history</Link> to verify completion and rejected rows.</li>
        </ol>
        <p>API base: <code className="break-all">{base}</code>. Override with <code>POL_API_BASE</code> for a separately approved endpoint. Use distinct keys and configuration for each client company.</p>
        <p className="text-xs text-ink-500">This template accepts one batch in memory. Split large source files according to API limits, and reconcile each returned run. A hosted, versioned Python runner with isolation and approval is still a separate product dependency.</p>
      </CardContent></Card>
    </div>
  );
}
