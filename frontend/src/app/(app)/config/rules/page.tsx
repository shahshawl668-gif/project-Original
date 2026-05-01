"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { apiJson } from "@/lib/api";

type Pref = { rule_id: string; suppressed: boolean };

export default function RulePreferencesPage() {
  const qc = useQueryClient();
  const [ruleId, setRuleId] = useState("");

  const list = useQuery({
    queryKey: ["rule-preferences"],
    queryFn: () => apiJson<Pref[]>("/api/rule-preferences"),
  });

  const upsert = useMutation({
    mutationFn: (body: { rule_id: string; suppressed: boolean }) =>
      apiJson("/api/rule-preferences", { method: "PUT", body: JSON.stringify(body) }),
    onSuccess: () => {
      toast.success("Preference saved");
      void qc.invalidateQueries({ queryKey: ["rule-preferences"] });
      setRuleId("");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const del = useMutation({
    mutationFn: (id: string) =>
      apiJson(`/api/rule-preferences/${encodeURIComponent(id)}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Removed");
      void qc.invalidateQueries({ queryKey: ["rule-preferences"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const add = () => {
    const rid = ruleId.trim();
    if (!rid) {
      toast.error("Enter a rule id (e.g. STAT-001, MOM-002)");
      return;
    }
    upsert.mutate({ rule_id: rid, suppressed: true });
  };

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Suppressed validation rules</h1>
        <p className="text-sm text-slate-600 mt-1">
          Hide specific rule findings for your tenant after payroll validation and in Excel export summaries. This does
          not change statutory calculations — only the reported findings.
        </p>
      </div>

      {list.isError && (
        <p className="text-sm text-red-600" role="alert">
          {(list.error as Error).message}
        </p>
      )}

      <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-3">
        <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Add rule id</p>
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            value={ruleId}
            onChange={(e) => setRuleId(e.target.value)}
            placeholder="e.g. STAT-006"
            className="flex-1 rounded-lg border border-slate-200 px-3 py-2 text-sm font-mono"
          />
          <button
            type="button"
            onClick={add}
            disabled={upsert.isPending}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            <Plus size={16} /> Suppress
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-100 flex items-center gap-2 text-sm font-medium text-slate-800">
          <Ban size={16} className="text-slate-400" />
          Active suppressions
        </div>
        {list.isPending ? (
          <p className="p-4 text-sm text-slate-500">Loading…</p>
        ) : !list.data?.length ? (
          <p className="p-4 text-sm text-slate-500">No rules suppressed — all findings will appear in validation.</p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {list.data.map((p) => (
              <li key={p.rule_id} className="flex items-center justify-between px-4 py-3 text-sm">
                <code className="font-mono text-slate-800">{p.rule_id}</code>
                <button
                  type="button"
                  onClick={() => del.mutate(p.rule_id)}
                  disabled={del.isPending}
                  className="text-red-600 hover:text-red-800 p-1 rounded-md hover:bg-red-50"
                  title="Remove suppression"
                >
                  <Trash2 size={16} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
