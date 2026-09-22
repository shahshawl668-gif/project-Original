"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, GripVertical, Loader2, Plus, Save, Trash2 } from "lucide-react";

import { Menu, MenuItem } from "@/components/cost/Menu";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import {
  approveTemplate,
  deleteTemplate,
  fetchJvOptions,
  fetchJvPresets,
  fetchTemplate,
  fetchTemplates,
  saveTemplate,
  type JvMeasureMeta,
  type JvRule,
  type JvTemplate,
} from "@/lib/reconciliation";

type Draft = {
  name: string;
  note: string;
  posting_basis: string;
  split_mode: string;
  group_by: string;
  detail_level: string;
  sign_convention: string;
  net_pay_source: string;
  voucher_date_rule: string;
  voucher_type: string;
  narration_template: string;
  export_format: string;
  balance_tolerance: number;
  rounding_mode: string;
  rounding_account: string;
  rules: JvRule[];
};

const BLANK: Draft = {
  name: "",
  note: "",
  posting_basis: "accrual",
  split_mode: "consolidated",
  group_by: "",
  detail_level: "summary",
  sign_convention: "two_column",
  net_pay_source: "computed",
  voucher_date_rule: "month_end",
  voucher_type: "Journal",
  narration_template: "Payroll for {period_label}{scope_suffix}",
  export_format: "generic_csv",
  balance_tolerance: 1,
  rounding_mode: "none",
  rounding_account: "",
  rules: [],
};

/**
 * Journal voucher templates.
 *
 * Every company posts payroll differently — its own chart of accounts, its own
 * split, its own policy on gratuity — so the mapping is data. What a rule maps
 * to is not a column but a *measure* from the cost taxonomy, which is why a
 * voucher built here can never disagree with the cost dashboard.
 */
export default function JvTemplatesPage() {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft>(BLANK);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const { data: options } = useQuery({ queryKey: ["jv-options"], queryFn: fetchJvOptions });
  const { data: presets } = useQuery({ queryKey: ["jv-presets"], queryFn: fetchJvPresets });
  const { data: templates } = useQuery({ queryKey: ["jv-templates"], queryFn: fetchTemplates });

  const save = useMutation({
    mutationFn: () =>
      saveTemplate(
        { ...draft, group_by: draft.group_by || null, rounding_account: draft.rounding_account || null },
        editingId ?? undefined,
      ),
    onSuccess: (template) => {
      setError(null);
      setSaved(
        template.state === "draft" && template.approved_by === null
          ? `Saved ${template.name}. It is a draft until an owner or manager approves it.`
          : `Saved ${template.name}.`,
      );
      setEditingId(template.id);
      queryClient.invalidateQueries({ queryKey: ["jv-templates"] });
    },
    onError: (err: Error) => setError(err.message),
  });

  const approve = useMutation({
    mutationFn: (id: string) => approveTemplate(id),
    onSuccess: (template) => {
      setError(null);
      setSaved(`${template.name} is now the mapping this entity posts with.`);
      queryClient.invalidateQueries({ queryKey: ["jv-templates"] });
    },
    onError: (err: Error) => setError(err.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteTemplate(id),
    onSuccess: () => {
      setDraft(BLANK);
      setEditingId(null);
      queryClient.invalidateQueries({ queryKey: ["jv-templates"] });
    },
    onError: (err: Error) => setError(err.message),
  });

  async function edit(template: JvTemplate) {
    const full = await fetchTemplate(template.id);
    setDraft({
      name: full.name,
      note: full.note ?? "",
      posting_basis: full.posting_basis,
      split_mode: full.split_mode,
      group_by: full.group_by ?? "",
      detail_level: full.detail_level,
      sign_convention: full.sign_convention,
      net_pay_source: full.net_pay_source,
      voucher_date_rule: full.voucher_date_rule,
      voucher_type: full.voucher_type,
      narration_template: full.narration_template,
      export_format: full.export_format,
      balance_tolerance: full.balance_tolerance,
      rounding_mode: full.rounding_mode,
      rounding_account: full.rounding_account ?? "",
      rules: full.rules ?? [],
    });
    setEditingId(full.id);
    setSaved(null);
  }

  const measures = options?.measures ?? [];
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  function updateRule(index: number, patch: Partial<JvRule>) {
    setDraft((current) => ({
      ...current,
      rules: current.rules.map((rule, i) => (i === index ? { ...rule, ...patch } : rule)),
    }));
  }

  const mapped = draft.rules
    .filter((rule) => rule.active)
    .flatMap((rule) => rule.measures);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Journal voucher templates"
        description="How this company turns a month of payroll cost into a voucher its ledger accepts."
      />

      {error && (
        <AlertBanner variant="error" title="That did not work">
          {error}
        </AlertBanner>
      )}
      {saved && (
        <AlertBanner variant="success" title="Saved">
          {saved}
        </AlertBanner>
      )}

      <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
        <Card>
          <CardContent className="py-5">
            <div className="flex items-center justify-between pb-3">
              <h3 className="text-sm font-semibold text-ink-900 dark:text-white">Templates</h3>
              <button
                type="button"
                onClick={() => {
                  setDraft(BLANK);
                  setEditingId(null);
                }}
                className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline dark:text-brand-300"
              >
                <Plus size={12} /> New
              </button>
            </div>
            {templates?.templates.length ? (
              <div className="space-y-1">
                {templates.templates.map((template) => (
                  <div key={template.id} className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => void edit(template)}
                      className={`min-w-0 flex-1 rounded-lg px-2 py-1.5 text-left text-sm transition hover:bg-ink-50 dark:hover:bg-ink-800 ${
                        template.id === editingId
                          ? "font-semibold text-brand-600 dark:text-brand-300"
                          : "text-ink-700 dark:text-ink-200"
                      }`}
                    >
                      <span className="block truncate">{template.name}</span>
                      <span className="block text-[10px] uppercase tracking-wide text-ink-400">
                        {template.is_current ? "current" : template.state} ·{" "}
                        {template.rule_count} rules
                      </span>
                    </button>
                    {template.state !== "approved" && (
                      <button
                        type="button"
                        onClick={() => remove.mutate(template.id)}
                        className="text-ink-400 transition hover:text-danger-600"
                        aria-label={`Delete ${template.name}`}
                      >
                        <Trash2 size={13} />
                      </button>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-ink-500 dark:text-ink-400">None yet.</p>
            )}

            <h3 className="pb-2 pt-5 text-sm font-semibold text-ink-900 dark:text-white">
              Start from
            </h3>
            <div className="space-y-1">
              {presets?.presets.map((preset) => (
                <button
                  key={preset.key}
                  type="button"
                  onClick={() => {
                    setDraft({
                      ...BLANK,
                      name: preset.name,
                      note: preset.note,
                      posting_basis: preset.posting_basis,
                      split_mode: preset.split_mode,
                      detail_level: preset.detail_level,
                      group_by: preset.group_by ?? "",
                      sign_convention: preset.sign_convention,
                      net_pay_source: preset.net_pay_source,
                      rules: preset.rules.map((rule) => ({
                        ...rule,
                        account_name: rule.account_name ?? null,
                        filters: rule.filters ?? {},
                        cost_center_from: rule.cost_center_from ?? null,
                        active: rule.active ?? true,
                      })),
                    });
                    setEditingId(null);
                    setSaved(null);
                  }}
                  className="block w-full rounded-lg px-2 py-1.5 text-left text-sm text-ink-700 transition hover:bg-ink-50 dark:text-ink-200 dark:hover:bg-ink-800"
                >
                  {preset.name}
                  <span className="block text-[11px] text-ink-500 dark:text-ink-400">
                    {preset.rule_count} rules
                  </span>
                </button>
              ))}
            </div>
            {presets?.caveat && (
              <p className="pt-3 text-[11px] leading-relaxed text-warning-700 dark:text-warning-300">
                {presets.caveat}
              </p>
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardContent className="space-y-4 py-5">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Template name">
                  <input
                    value={draft.name}
                    onChange={(event) => set("name", event.target.value)}
                    placeholder="Monthly payroll JV"
                    className={inputClass}
                  />
                </Field>
                <Field label="Narration">
                  <input
                    value={draft.narration_template}
                    onChange={(event) => set("narration_template", event.target.value)}
                    className={inputClass}
                  />
                </Field>
              </div>

              <div className="flex flex-wrap items-end gap-3">
                <Choice
                  label="Posting basis"
                  options={options?.posting_bases ?? []}
                  value={draft.posting_basis}
                  onChange={(value) => set("posting_basis", value)}
                />
                <Choice
                  label="Split"
                  options={options?.split_modes ?? []}
                  value={draft.split_mode}
                  onChange={(value) => set("split_mode", value)}
                />
                <Choice
                  label="Cost centre is"
                  options={options?.group_by ?? []}
                  value={draft.group_by}
                  onChange={(value) => set("group_by", value)}
                />
                <Choice
                  label="Detail"
                  options={options?.detail_levels ?? []}
                  value={draft.detail_level}
                  onChange={(value) => set("detail_level", value)}
                />
              </div>

              <div className="flex flex-wrap items-end gap-3">
                <Choice
                  label="Net pay from"
                  options={options?.net_pay_sources ?? []}
                  value={draft.net_pay_source}
                  onChange={(value) => set("net_pay_source", value)}
                />
                <Choice
                  label="Voucher date"
                  options={options?.voucher_date_rules ?? []}
                  value={draft.voucher_date_rule}
                  onChange={(value) => set("voucher_date_rule", value)}
                />
                <Choice
                  label="Amount columns"
                  options={options?.sign_conventions ?? []}
                  value={draft.sign_convention}
                  onChange={(value) => set("sign_convention", value)}
                />
                <Choice
                  label="Export as"
                  options={options?.export_formats ?? []}
                  value={draft.export_format}
                  onChange={(value) => set("export_format", value)}
                />
                <Choice
                  label="Rounding"
                  options={options?.rounding_modes ?? []}
                  value={draft.rounding_mode}
                  onChange={(value) => set("rounding_mode", value)}
                />
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="Tolerance (₹)" hint="Above this, a difference is a mapping error.">
                  <input
                    type="number"
                    min={0}
                    step="0.01"
                    value={draft.balance_tolerance}
                    onChange={(event) => set("balance_tolerance", Number(event.target.value))}
                    className={inputClass}
                  />
                </Field>
                {draft.rounding_mode === "account" && (
                  <Field label="Rounding account">
                    <input
                      value={draft.rounding_account}
                      onChange={(event) => set("rounding_account", event.target.value)}
                      className={inputClass}
                    />
                  </Field>
                )}
                <Field label="Voucher type">
                  <input
                    value={draft.voucher_type}
                    onChange={(event) => set("voucher_type", event.target.value)}
                    className={inputClass}
                  />
                </Field>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="py-5">
              <div className="flex flex-wrap items-center justify-between gap-3 pb-3">
                <div>
                  <h3 className="text-base font-semibold text-ink-900 dark:text-white">
                    Posting rules
                  </h3>
                  <p className="text-xs text-ink-500 dark:text-ink-400">
                    Each line maps cost measures to one account. A correct mapping balances
                    by arithmetic — debits are gross plus employer cost, credits are the
                    liabilities plus net.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    setDraft((current) => ({
                      ...current,
                      rules: [
                        ...current.rules,
                        {
                          label: "New line",
                          account_code: "",
                          account_name: null,
                          side: "debit",
                          measures: [],
                          filters: {},
                          cost_center_from: null,
                          active: true,
                        },
                      ],
                    }))
                  }
                  className="inline-flex h-9 items-center gap-2 rounded-lg border border-ink-200 px-3 text-sm font-medium text-ink-700 transition hover:bg-ink-50 dark:border-ink-700 dark:text-ink-200 dark:hover:bg-ink-800"
                >
                  <Plus size={14} /> Add a line
                </button>
              </div>

              {draft.rules.length === 0 ? (
                <p className="py-6 text-center text-sm text-ink-500 dark:text-ink-400">
                  No rules yet. Start from a supplied template on the left, then change the
                  account codes to your own.
                </p>
              ) : (
                <div className="space-y-2">
                  {draft.rules.map((rule, index) => (
                    <div
                      key={index}
                      className="rounded-xl border border-ink-200/70 p-3 dark:border-ink-700/60"
                    >
                      <div className="flex flex-wrap items-end gap-2">
                        <GripVertical size={14} className="mb-2.5 text-ink-300" />
                        <div className="min-w-[10rem] flex-1">
                          <Field label="Line">
                            <input
                              value={rule.label}
                              onChange={(event) =>
                                updateRule(index, { label: event.target.value })
                              }
                              className={inputClass}
                            />
                          </Field>
                        </div>
                        <div className="w-28">
                          <Field label="Account">
                            <input
                              value={rule.account_code}
                              onChange={(event) =>
                                updateRule(index, { account_code: event.target.value })
                              }
                              className={inputClass}
                            />
                          </Field>
                        </div>
                        <Choice
                          label="Side"
                          options={options?.sides ?? []}
                          value={rule.side}
                          onChange={(value) =>
                            updateRule(index, { side: value as "debit" | "credit" })
                          }
                        />
                        <button
                          type="button"
                          onClick={() =>
                            setDraft((current) => ({
                              ...current,
                              rules: current.rules.filter((_, i) => i !== index),
                            }))
                          }
                          className="mb-1 p-1.5 text-ink-400 transition hover:text-danger-600"
                          aria-label={`Remove ${rule.label}`}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>

                      <div className="pt-2">
                        <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wide text-ink-400">
                          Measures this line posts
                        </span>
                        <div className="flex flex-wrap gap-1.5">
                          {measures.map((measure) => {
                            const on = rule.measures.includes(measure.key);
                            return (
                              <button
                                key={measure.key}
                                type="button"
                                title={measure.hint}
                                onClick={() =>
                                  updateRule(index, {
                                    measures: on
                                      ? rule.measures.filter((m) => m !== measure.key)
                                      : [...rule.measures, measure.key],
                                  })
                                }
                                className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition ${
                                  on
                                    ? "bg-brand-600 text-white"
                                    : "bg-ink-100 text-ink-600 hover:bg-ink-200 dark:bg-ink-800 dark:text-ink-300 dark:hover:bg-ink-700"
                                }`}
                              >
                                {measure.label}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <Coverage measures={measures} mapped={mapped} />

              <div className="flex flex-wrap items-center gap-2 pt-4">
                <button
                  type="button"
                  onClick={() => save.mutate()}
                  disabled={!draft.name || save.isPending}
                  className="inline-flex h-9 items-center gap-2 rounded-lg bg-brand-600 px-3 text-sm font-medium text-white transition hover:bg-brand-700 disabled:opacity-50"
                >
                  {save.isPending ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Save size={14} />
                  )}
                  {editingId ? "Save changes" : "Save template"}
                </button>
                {editingId && (
                  <button
                    type="button"
                    onClick={() => approve.mutate(editingId)}
                    disabled={approve.isPending}
                    className="inline-flex h-9 items-center gap-2 rounded-lg border border-ink-200 px-3 text-sm font-medium text-ink-700 transition hover:bg-ink-50 disabled:opacity-50 dark:border-ink-700 dark:text-ink-200 dark:hover:bg-ink-800"
                  >
                    {approve.isPending ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <CheckCircle2 size={14} />
                    )}
                    Approve as the current mapping
                  </button>
                )}
                <p className="text-xs text-ink-500 dark:text-ink-400">
                  Editing an approved template withdraws its approval — the mapping that
                  posts to the ledger is re-approved when it changes.
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

/**
 * Which parts of payroll cost this template has found a home for.
 *
 * Shown while editing rather than only on preview, because the cheapest moment
 * to notice that nothing credits TDS payable is before the voucher is built.
 */
function Coverage({
  measures,
  mapped,
}: {
  measures: JvMeasureMeta[];
  mapped: string[];
}) {
  // What each measure stands for comes from the API, so this indicator and the
  // voucher's own coverage check can never disagree about whether "gross"
  // covers HRA.
  const parts = new Map(measures.map((measure) => [measure.key, measure.parts]));
  const covered = new Set(mapped.flatMap((key) => parts.get(key) ?? [key]));
  const base = measures.filter((measure) => !measure.derived);
  const missing = base.filter((measure) => !covered.has(measure.key));

  if (!base.length) return null;

  return (
    <div className="mt-4 rounded-xl border border-ink-200/70 px-4 py-3 dark:border-ink-700/60">
      <p className="pb-2 text-xs font-semibold text-ink-700 dark:text-ink-200">
        {missing.length === 0
          ? "Every part of payroll cost is mapped to an account."
          : `${missing.length} part(s) of payroll cost have no account yet.`}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {base.map((measure) => (
          <span
            key={measure.key}
            className={`rounded-full px-2 py-0.5 text-[11px] ${
              covered.has(measure.key)
                ? "bg-success-500/10 text-success-700 dark:text-success-300"
                : "bg-danger-500/10 text-danger-700 dark:text-danger-300"
            }`}
          >
            {measure.label}
          </span>
        ))}
      </div>
      {missing.length > 0 && (
        <p className="pt-2 text-[11px] text-ink-500 dark:text-ink-400">
          An unmapped measure is missing from the voucher entirely, and the voucher will not
          balance by exactly that amount.
        </p>
      )}
    </div>
  );
}

const inputClass =
  "h-9 w-full rounded-lg border border-ink-200 bg-white px-3 text-sm text-ink-900 placeholder:text-ink-400 dark:border-ink-700 dark:bg-ink-900 dark:text-white";

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <span className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wide text-ink-400">
        {label}
      </span>
      {children}
      {hint && <p className="pt-1 text-[11px] text-ink-500 dark:text-ink-400">{hint}</p>}
    </div>
  );
}

function Choice({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { key: string; label: string; hint?: string }[];
  value: string;
  onChange: (value: string) => void;
}) {
  const current = options.find((option) => option.key === value);
  return (
    <Menu label={label} summary={current?.label ?? (value || "—")} width="w-80">
      {(close) => (
        <>
          {options.map((option) => (
            <MenuItem
              key={option.key}
              selected={option.key === value}
              hint={option.hint}
              onClick={() => {
                onChange(option.key);
                close();
              }}
            >
              {option.label}
            </MenuItem>
          ))}
        </>
      )}
    </Menu>
  );
}
