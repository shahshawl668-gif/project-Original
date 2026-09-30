"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowRight, CheckCircle2, RotateCcw, Rocket, Send, XCircle } from "lucide-react";

import { useEntity } from "@/context/EntityContext";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { BackLink } from "@/components/layout/BackLink";
import { ConfirmAction } from "@/components/studio/Controls";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StudioNav } from "@/components/studio/StudioNav";
import { StatusBadge, fmtTime } from "@/components/studio/RunBits";
import { RELEASE_VARIANT, studioReleaseApi, type Release } from "@/lib/studio";

const MANAGE = new Set(["owner", "manager"]);
const CHANGE_VARIANT = { create: "primary", update: "warning", unchanged: "secondary", retire: "destructive", disable: "destructive" } as const;

export default function ReleasePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { entity, activeRole } = useEntity();
  const qc = useQueryClient();
  const canManage = MANAGE.has(activeRole ?? "");
  const q = useQuery({ queryKey: ["studio-release", entity?.id, id], queryFn: () => studioReleaseApi.get(id), enabled: !!entity && !!id, retry: false });
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<"promote" | "cancel" | null>(null);
  if (q.error) return <AlertBanner variant="error" title="This release could not be opened">It may belong to another organisation. <Link className="underline" href="/studio/releases">All releases</Link></AlertBanner>;
  const r = q.data;
  if (!r) return <Skeleton className="h-96 w-full rounded-2xl" />;
  const act = async (fn: () => Promise<Release>, done: string) => {
    setBusy(true);
    try {
      const out = await fn();
      toast.success(done);
      await qc.invalidateQueries({ queryKey: ["studio-release", entity?.id, id] });
      if (out.id !== r.id) router.push(`/studio/releases/${out.id}`);
    } catch (e) { toast.error("Refused", { description: e instanceof Error ? e.message : "" }); }
    finally { setBusy(false); }
  };
  const impact = r.impact;
  return (
    <div className="space-y-5">
      <BackLink fallback="/studio/releases">All releases</BackLink>
      <PageHeader eyebrow={r.rollback_of_id ? "PeopleOps Studio · rollback release" : "PeopleOps Studio · release"}
        title={<span className="flex flex-wrap items-center gap-3">{r.title} <Badge variant={RELEASE_VARIANT[r.status]}>{r.status.replace("_", " ")}</Badge></span>}
        description={`${r.source.name} (${r.source.environment}) → ${r.target.name} (${r.target.environment}) · drafted by ${r.created_by} ${fmtTime(r.created_at)}`} />
      <StudioNav />
      {r.notes ? <p className="text-sm text-ink-600">{r.notes}</p> : null}
      {r.rollback_of_id ? <AlertBanner variant="info" title="Restores what an earlier release replaced">As new versions: nothing already published is edited. <Link className="underline" href={`/studio/releases/${r.rollback_of_id}`}>The release it undoes</Link></AlertBanner> : null}

      {impact ? (
        <Card><CardContent className="space-y-3 py-5" data-testid="impact">
          <h2 className="text-base font-semibold text-ink-900">Impact on {r.target.name}</h2>
          {impact.blocking ? <AlertBanner variant="error" title={`${impact.blocking} blocking problem(s)`}>It cannot be submitted or promoted until these are fixed in {r.target.name}.</AlertBanner> : null}
          <ul className="space-y-2">{impact.items.map((i) => (
            <li key={`${i.kind}:${i.name}`} className="rounded-xl border border-ink-200 p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-semibold">{i.kind.replace("_", " ")} · {i.name}</span>
                <span className="flex items-center gap-2 text-xs text-ink-500">
                  {i.target_version ? `v${i.target_version} in force there` : "not there yet"}{i.source_version ? <> <ArrowRight size={11} /> v{i.source_version} from {r.source.name}</> : null}
                  <Badge variant={CHANGE_VARIANT[i.change]}>{i.change}</Badge></span>
              </div>
              {i.diff.length ? <ul className="mt-1 list-disc pl-5 text-xs text-ink-600">{i.diff.slice(0, 12).map((d, k) => (
                <li key={k}>{String(d.target ?? d.part ?? "")} {String(d.change ?? "")}{d.before !== undefined && d.after !== undefined && typeof d.before !== "object" ? `: ${String(d.before)} → ${String(d.after)}` : ""}</li>))}</ul> : null}
              {i.tested ? <p className="mt-1 text-xs">Tried in {r.source.name}: <Link className="underline" href={`/studio/runs/${i.tested.run_id}`}>run</Link> <StatusBadge status={i.tested.status} /></p> : null}
              {i.blocking.map((b) => <p key={b} className="mt-1 text-xs text-danger-700">✗ {b}</p>)}
              {i.warnings.map((w) => <p key={w} className="mt-1 text-xs text-warning-800">! {w}</p>)}
            </li>))}</ul>
        </CardContent></Card>
      ) : null}

      {r.result ? (
        <Card><CardContent className="space-y-2 py-5">
          <h2 className="text-base font-semibold text-ink-900">Promoted {fmtTime(r.promoted_at)} by {r.promoted_by}</h2>
          <ul className="text-sm">{r.result.map((x) => <li key={`${x.kind}:${x.name}`}><CheckCircle2 size={13} className="mr-1 inline text-success-600" />{x.kind} {x.name}: {x.outcome}{x.version ? ` (v${x.version})` : ""}</li>)}</ul>
          <p className="text-xs text-ink-500">Approved by {r.decided_by}{r.decision_note ? ` — “${r.decision_note}”` : ""}. Every earlier version, and every run that used one, is unchanged.</p>
        </CardContent></Card>
      ) : null}
      {r.status === "rejected" ? <AlertBanner variant="error" title={`Rejected by ${r.decided_by}`}>{r.decision_note}</AlertBanner> : null}

      {canManage ? (
        <Card><CardContent className="flex flex-wrap items-center gap-2 py-5">
          {r.status === "draft" ? <Button disabled={busy || !!impact?.blocking} onClick={() => void act(() => studioReleaseApi.act(r.id, "submit"), "Submitted for approval")}><Send size={14} /> Submit for approval</Button> : null}
          {r.status === "awaiting_approval" ? <>
            <input aria-label="Decision note" className="min-w-[16rem] flex-1 rounded-lg border border-ink-200 px-3 py-2 text-sm" placeholder="Note (required to reject)" value={note} onChange={(e) => setNote(e.target.value)} />
            <Button disabled={busy} onClick={() => void act(() => studioReleaseApi.decide(r.id, true, note), "Approved")}><CheckCircle2 size={14} /> Approve</Button>
            <Button variant="destructive-outline" disabled={busy || !note.trim()} title={note.trim() ? undefined : "Write a note saying why"} onClick={() => void act(() => studioReleaseApi.decide(r.id, false, note), "Rejected")}><XCircle size={14} /> Reject</Button>
            <span className="text-xs text-ink-500">An owner or manager other than {r.created_by} decides.</span>
          </> : null}
          {r.status === "approved" ? <Button disabled={busy || !!impact?.blocking} onClick={() => setConfirm("promote")}><Rocket size={14} /> Promote to {r.target.name}</Button> : null}
          {r.can_roll_back ? <Button variant="outline" disabled={busy} onClick={() => void act(() => studioReleaseApi.act(r.id, "rollback"), "Rollback drafted")}><RotateCcw size={14} /> Draft a rollback</Button> : null}
          {["draft", "awaiting_approval", "approved"].includes(r.status) ? <Button variant="destructive-outline" className="ml-auto" disabled={busy} onClick={() => setConfirm("cancel")}>Cancel release</Button> : null}
        </CardContent></Card>
      ) : null}
      <ConfirmAction
        open={confirm === "promote"}
        onClose={() => setConfirm(null)}
        tone="primary"
        title={`Promote to ${r.target.name} (${r.target.environment})?`}
        consequence={<>Every item marked create or update becomes the version in force in {r.target.name} from now. Earlier versions, and every run that used one, stay as they are; a rollback is drafted as a new release, not an undo.</>}
        confirmLabel={`Promote to ${r.target.name}`}
        onConfirm={() => act(() => studioReleaseApi.act(r.id, "promote"), "Promoted")}
      />
      <ConfirmAction
        open={confirm === "cancel"}
        onClose={() => setConfirm(null)}
        title="Cancel this release?"
        consequence="It stops here and cannot be submitted or promoted. Nothing in either company changes. Draft a new release to try again."
        confirmLabel="Cancel release"
        onConfirm={() => act(() => studioReleaseApi.act(r.id, "cancel"), "Cancelled")}
      />
    </div>
  );
}
