"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CalendarClock } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/drawer";
import { StatusPill } from "@/components/ui/status-pill";
import { useEntity } from "@/context/EntityContext";
import { dateTime, plural } from "@/lib/format";
import { statutoryVersionsApi, type StatutoryVersion } from "@/lib/statutory-config";
import { periodLabel } from "@/lib/workspace";

const MANAGERS = new Set(["owner", "manager"]);
const PILL: Record<StatutoryVersion["status"], { tone: "neutral" | "success" | "warning"; label: string }> = {
  draft: { tone: "warning", label: "Draft — not in force" },
  published: { tone: "success", label: "Published" },
  withdrawn: { tone: "neutral", label: "Withdrawn" },
};

const show = (v: unknown) =>
  v === null || v === undefined || v === "" ? "—" : Array.isArray(v) ? (v.length ? v.join(", ") : "none") : typeof v === "object" ? JSON.stringify(v) : String(v);

/**
 * Changes to PF, ESIC and column mapping that take effect from a month.
 *
 * A draft changes nothing. Publishing puts it in force from its month until
 * the next change, for validation and costing; the validated months it covers
 * are then marked revalidation required, and the panel names them before
 * anyone presses the button. Withdrawing puts those months back.
 */
export function DatedChanges() {
  const { entity, activeRole } = useEntity();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["statutory-versions", entity?.id], queryFn: statutoryVersionsApi.list, enabled: !!entity });
  const [busy, setBusy] = useState<string | null>(null);
  const [withdrawing, setWithdrawing] = useState<StatutoryVersion | null>(null);
  const [reason, setReason] = useState("");
  const [publishing, setPublishing] = useState<StatutoryVersion | null>(null);
  const isManager = MANAGERS.has(activeRole ?? "");
  const canWrite = activeRole !== "viewer";

  async function act(id: string, fn: () => Promise<unknown>, done: string) {
    setBusy(id);
    try {
      await fn();
      toast.success(done);
      await qc.invalidateQueries({ queryKey: ["statutory-versions", entity?.id] });
    } catch (e) {
      toast.error("Refused", { description: e instanceof Error ? e.message : "" });
    } finally {
      setBusy(null);
    }
  }

  const data = q.data;
  const now = data?.in_force_now;
  return (
    <section aria-labelledby="dated-heading" className="rounded-xl border border-ink-200 bg-white p-5 shadow-soft">
      <h2 id="dated-heading" className="flex items-center gap-2 text-[15px] font-semibold text-ink-900"><CalendarClock size={16} className="text-ink-500" aria-hidden /> Dated changes</h2>
      <p className="mt-1 text-[13px] text-ink-600">
        A change that takes effect from a month — a new ceiling from April, say — is drafted here and published when it is right. Months before it keep the configuration above.
        {now ? <> In force this month: <b>{now.version ? `change ${now.version}, from ${periodLabel(now.effective_from!)}` : "the configuration above"}</b>.</> : null}
        {data?.independent_publish ? " Your organisation requires someone other than the author to publish." : ""}
      </p>
      {q.isLoading ? <p className="mt-3 text-xs text-ink-500">Loading…</p> : !data?.versions.length ? (
        <p className="mt-3 text-[13px] text-ink-500">None yet. Edit the configuration above and choose <b>Schedule from a month…</b> in the bar at the foot of the page.</p>
      ) : (
        <ol className="mt-3 divide-y divide-ink-100 rounded-lg border border-ink-200">
          {data.versions.map((v) => (
            <li key={v.id} className="space-y-2 px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-[13px] font-semibold text-ink-900">
                  Change {v.number} · from {periodLabel(v.effective_from)}{v.covers_until ? ` to before ${periodLabel(v.covers_until)}` : ""}
                </p>
                <StatusPill tone={PILL[v.status].tone}>{PILL[v.status].label}</StatusPill>
              </div>
              <p className="text-xs text-ink-500">
                Drafted by {v.created_by ?? "someone no longer here"} {dateTime(v.created_at)}
                {v.published_at ? ` · published by ${v.published_by ?? "—"} ${dateTime(v.published_at)}` : ""}
                {v.withdrawn_at ? ` · withdrawn by ${v.withdrawn_by ?? "—"} ${dateTime(v.withdrawn_at)}: ${v.withdraw_reason}` : ""}
              </p>
              {v.note ? <p className="text-[13px] text-ink-700">{v.note}</p> : null}
              {v.changes.length ? (
                <ul className="text-xs text-ink-700">
                  {v.changes.slice(0, 6).map((c) => (
                    <li key={c.field}><span className="text-ink-500">{c.field.replace(/_/g, " ").replace(/\./g, " › ")}:</span> <span className="line-through decoration-ink-300">{show(c.before)}</span> → <b>{show(c.after)}</b></li>
                  ))}
                  {v.changes.length > 6 ? <li className="text-ink-500">and {v.changes.length - 6} more</li> : null}
                </ul>
              ) : <p className="text-xs text-ink-500">Identical to the configuration before its month.</p>}
              {v.status !== "withdrawn" ? (
                <p className="text-xs text-ink-700">{v.affected_months.length
                  ? `${v.status === "draft" ? "Publishing marks" : "It covers"} ${plural(v.affected_months.length, "validated month")} (${v.affected_months.map(periodLabel).join(", ")})${v.status === "draft" ? " as needing revalidation." : "."}`
                  : "No validated month is covered yet."}</p>
              ) : null}
              {canWrite ? (
                <div className="flex flex-wrap gap-2 pt-1">
                  {v.status === "draft" && isManager ? <Button size="sm" disabled={!!busy} onClick={() => setPublishing(v)}>Publish…</Button> : null}
                  {v.status === "draft" ? <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => void act(v.id, () => statutoryVersionsApi.discard(v.id), `Change ${v.number} discarded`)}>Discard draft</Button> : null}
                  {v.status === "published" && isManager ? <Button size="sm" variant="destructive-outline" disabled={!!busy} onClick={() => { setReason(""); setWithdrawing(v); }}>Withdraw…</Button> : null}
                  {v.status === "draft" && !isManager ? <span className="text-xs text-ink-500">A manager or owner publishes it.</span> : null}
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      )}

      <Dialog
        open={!!publishing}
        onClose={() => setPublishing(null)}
        title={publishing ? `Publish change ${publishing.number} from ${periodLabel(publishing.effective_from)}?` : ""}
        description="It is in force from its month for validation and costing. Months before it are unaffected."
        footer={<>
          <Button variant="outline" onClick={() => setPublishing(null)}>Cancel</Button>
          <Button disabled={!!busy} onClick={() => { const v = publishing!; setPublishing(null); void act(v.id, () => statutoryVersionsApi.publish(v.id), `Change ${v.number} published`); }}>Publish</Button>
        </>}
      >
        {publishing?.affected_months.length ? (
          <p className="text-[13px] text-warning-800">{plural(publishing.affected_months.length, "validated month")} — {publishing.affected_months.map(periodLabel).join(", ")} — will say revalidation is required, naming the configuration. A signed-off month is not reopened, but it will no longer match today&apos;s configuration.</p>
        ) : <p className="text-[13px] text-ink-700">No validated month is affected.</p>}
      </Dialog>

      <Dialog
        open={!!withdrawing}
        onClose={() => setWithdrawing(null)}
        title={withdrawing ? `Withdraw change ${withdrawing.number}?` : ""}
        description="Its months fall back to the change before it, or the configuration above. The withdrawal and your reason are kept."
        footer={<>
          <Button variant="outline" onClick={() => setWithdrawing(null)}>Keep it</Button>
          <Button variant="destructive" disabled={reason.trim().length < 3 || !!busy}
            onClick={() => { const v = withdrawing!; setWithdrawing(null); void act(v.id, () => statutoryVersionsApi.withdraw(v.id, reason.trim()), `Change ${v.number} withdrawn`); }}>Withdraw</Button>
        </>}
      >
        <label className="block text-xs font-medium text-ink-700">Reason (required)
          <textarea className="mt-1 block min-h-[64px] w-full rounded-lg border border-ink-200 bg-white px-2.5 py-2 text-[13px] text-ink-900" value={reason} maxLength={2000} onChange={(e) => setReason(e.target.value)} />
        </label>
        {withdrawing?.affected_months.length ? <p className="mt-2 text-[13px] text-warning-800">{plural(withdrawing.affected_months.length, "validated month")} will need revalidation.</p> : null}
      </Dialog>
    </section>
  );
}
