"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Loader2, Plus, Save, Trash2, Wand2 } from "lucide-react";

import { Menu, MenuItem } from "@/components/cost/Menu";
import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Card, CardContent } from "@/components/ui/card";
import { formatINR } from "@/lib/cost-analysis";
import {
  deleteProfile,
  fetchBankFields,
  fetchBankPresets,
  fetchProfiles,
  saveProfile,
  suggestMapping,
  testProfile,
  type BankProfile,
  type ProfileTest,
} from "@/lib/reconciliation";

type Draft = Omit<BankProfile, "id" | "created_at">;

const BLANK: Draft = {
  name: "",
  bank_label: "",
  note: "",
  kind: "payment_advice",
  layout: "delimited",
  delimiter: ",",
  encoding: "utf-8",
  has_header: true,
  skip_rows: 0,
  trailer_rows: 0,
  column_map: {},
  amount_unit: "rupees",
  amount_sign: "as_is",
  date_format: null,
  employee_id_transform: "trim",
  row_filter: {},
  is_default: false,
};

/**
 * Bank file profiles.
 *
 * A bank's payment file layout is data here rather than code, because it
 * differs at every client and changes without notice. The page is built around
 * the one step that makes a mapping safe: testing it against a real file and
 * showing what it produced, row by row, before it is trusted with a month of
 * payments.
 */
export default function BankProfilesPage() {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft>(BLANK);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [test, setTest] = useState<ProfileTest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const { data: catalogue } = useQuery({ queryKey: ["bank-fields"], queryFn: fetchBankFields });
  const { data: presets } = useQuery({ queryKey: ["bank-presets"], queryFn: fetchBankPresets });
  const { data: profiles } = useQuery({ queryKey: ["bank-profiles"], queryFn: fetchProfiles });

  const save = useMutation({
    mutationFn: () => saveProfile(draft, editingId ?? undefined),
    onSuccess: (profile) => {
      setError(null);
      setSaved(`Saved ${profile.name}.`);
      setEditingId(profile.id);
      queryClient.invalidateQueries({ queryKey: ["bank-profiles"] });
    },
    onError: (err: Error) => setError(err.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => deleteProfile(id),
    onSuccess: () => {
      reset();
      queryClient.invalidateQueries({ queryKey: ["bank-profiles"] });
    },
  });

  const runTest = useMutation({
    mutationFn: (file: File) => testProfile(file, draft),
    onSuccess: (result) => {
      setError(null);
      setTest(result);
    },
    onError: (err: Error) => {
      setTest(null);
      setError(err.message);
    },
  });

  const suggest = useMutation({
    mutationFn: (file: File) => suggestMapping(file, draft.delimiter),
    onSuccess: (result) => {
      setError(null);
      setDraft((current) => ({ ...current, column_map: { ...result.column_map } }));
    },
    onError: (err: Error) => setError(err.message),
  });

  function reset() {
    setDraft(BLANK);
    setEditingId(null);
    setTest(null);
    setSaved(null);
  }

  function edit(profile: BankProfile) {
    const { id, created_at: _created, ...rest } = profile;
    void _created;
    setDraft(rest);
    setEditingId(id);
    setTest(null);
    setSaved(null);
  }

  const fields = catalogue?.fields ?? [];
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Bank file profiles"
        description="How to read the payment file your bank sends. One profile per layout, defined once."
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
              <h3 className="text-sm font-semibold text-ink-900 dark:text-white">Saved</h3>
              <button
                type="button"
                onClick={reset}
                className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:underline dark:text-brand-300"
              >
                <Plus size={12} /> New
              </button>
            </div>
            {profiles?.profiles.length ? (
              <div className="space-y-1">
                {profiles.profiles.map((profile) => (
                  <div key={profile.id} className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => edit(profile)}
                      className={`min-w-0 flex-1 truncate rounded-lg px-2 py-1.5 text-left text-sm transition hover:bg-ink-50 dark:hover:bg-ink-800 ${
                        profile.id === editingId
                          ? "font-semibold text-brand-600 dark:text-brand-300"
                          : "text-ink-700 dark:text-ink-200"
                      }`}
                    >
                      {profile.name}
                      {profile.is_default && (
                        <span className="ml-1 text-[10px] uppercase text-ink-400">default</span>
                      )}
                    </button>
                    <button
                      type="button"
                      onClick={() => remove.mutate(profile.id)}
                      className="text-ink-400 transition hover:text-danger-600"
                      aria-label={`Delete ${profile.name}`}
                    >
                      <Trash2 size={13} />
                    </button>
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
                    const { key: _key, ...rest } = preset;
                    void _key;
                    setDraft({ ...BLANK, ...rest, name: preset.name });
                    setEditingId(null);
                    setTest(null);
                  }}
                  className="block w-full rounded-lg px-2 py-1.5 text-left text-sm text-ink-700 transition hover:bg-ink-50 dark:text-ink-200 dark:hover:bg-ink-800"
                >
                  {preset.name}
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
                <Field label="Profile name">
                  <input
                    value={draft.name}
                    onChange={(event) => set("name", event.target.value)}
                    placeholder="HDFC salary file"
                    className={inputClass}
                  />
                </Field>
                <Field label="Bank">
                  <input
                    value={draft.bank_label ?? ""}
                    onChange={(event) => set("bank_label", event.target.value)}
                    placeholder="HDFC Bank"
                    className={inputClass}
                  />
                </Field>
              </div>

              <div className="flex flex-wrap items-end gap-3">
                <Choice
                  label="File kind"
                  options={catalogue?.kinds ?? []}
                  value={draft.kind}
                  onChange={(value) => set("kind", value)}
                />
                <Choice
                  label="Layout"
                  options={catalogue?.layouts ?? []}
                  value={draft.layout}
                  onChange={(value) => set("layout", value)}
                />
                <Choice
                  label="Amount unit"
                  options={catalogue?.amount_units ?? []}
                  value={draft.amount_unit}
                  onChange={(value) => set("amount_unit", value)}
                />
                <Choice
                  label="Sign"
                  options={catalogue?.amount_signs ?? []}
                  value={draft.amount_sign}
                  onChange={(value) => set("amount_sign", value)}
                />
                <Choice
                  label="Employee code"
                  options={catalogue?.id_transforms ?? []}
                  value={draft.employee_id_transform}
                  onChange={(value) => set("employee_id_transform", value)}
                />
              </div>

              <div className="grid gap-3 sm:grid-cols-4">
                <Field label="Delimiter">
                  <input
                    value={draft.delimiter}
                    onChange={(event) => set("delimiter", event.target.value)}
                    className={inputClass}
                  />
                </Field>
                <Field label="Rows to skip">
                  <input
                    type="number"
                    min={0}
                    value={draft.skip_rows}
                    onChange={(event) => set("skip_rows", Number(event.target.value))}
                    className={inputClass}
                  />
                </Field>
                <Field label="Trailer rows">
                  <input
                    type="number"
                    min={0}
                    value={draft.trailer_rows}
                    onChange={(event) => set("trailer_rows", Number(event.target.value))}
                    className={inputClass}
                  />
                </Field>
                <Field label="Header row">
                  <label className="flex h-9 items-center gap-2 text-sm text-ink-700 dark:text-ink-200">
                    <input
                      type="checkbox"
                      checked={draft.has_header}
                      onChange={(event) => set("has_header", event.target.checked)}
                    />
                    File has one
                  </label>
                </Field>
              </div>

              <p className="text-xs text-ink-500 dark:text-ink-400">
                A control total on the last line is not a payment. Set trailer rows to drop
                it — it is then read as the file&apos;s own stated total and compared with the
                sum of the lines.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="py-5">
              <div className="flex flex-wrap items-center justify-between gap-3 pb-3">
                <div>
                  <h3 className="text-base font-semibold text-ink-900 dark:text-white">
                    Column mapping
                  </h3>
                  <p className="text-xs text-ink-500 dark:text-ink-400">
                    {draft.has_header
                      ? "Give the column name as the file writes it."
                      : "Give the column number, counting from 1."}
                  </p>
                </div>
                <label className="inline-flex h-9 cursor-pointer items-center gap-2 rounded-lg border border-ink-200 px-3 text-sm font-medium text-ink-700 transition hover:bg-ink-50 dark:border-ink-700 dark:text-ink-200 dark:hover:bg-ink-800">
                  {suggest.isPending ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Wand2 size={14} />
                  )}
                  Suggest from a file
                  <input
                    type="file"
                    accept=".csv,.txt,.xlsx"
                    className="hidden"
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) suggest.mutate(file);
                      event.target.value = "";
                    }}
                  />
                </label>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                {fields.map((field) => (
                  <Field
                    key={field.key}
                    label={`${field.label}${field.required ? " *" : ""}`}
                    hint={field.hint}
                  >
                    <input
                      value={String(draft.column_map[field.key] ?? "")}
                      onChange={(event) => {
                        const raw = event.target.value;
                        const parsed =
                          raw !== "" && !draft.has_header && /^\d+$/.test(raw)
                            ? Number(raw)
                            : raw;
                        setDraft((current) => {
                          const next = { ...current.column_map };
                          if (raw === "") delete next[field.key];
                          else next[field.key] = parsed;
                          return { ...current, column_map: next };
                        });
                      }}
                      className={inputClass}
                    />
                  </Field>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="py-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="text-base font-semibold text-ink-900 dark:text-white">
                    Test against a real file
                  </h3>
                  <p className="text-xs text-ink-500 dark:text-ink-400">
                    Nothing is stored. This is what the mapping would produce.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <label className="inline-flex h-9 cursor-pointer items-center gap-2 rounded-lg border border-ink-200 px-3 text-sm font-medium text-ink-700 transition hover:bg-ink-50 dark:border-ink-700 dark:text-ink-200 dark:hover:bg-ink-800">
                    {runTest.isPending ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <FlaskConical size={14} />
                    )}
                    Test
                    <input
                      type="file"
                      accept=".csv,.txt,.xlsx"
                      className="hidden"
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) runTest.mutate(file);
                        event.target.value = "";
                      }}
                    />
                  </label>
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
                    {editingId ? "Save changes" : "Save profile"}
                  </button>
                </div>
              </div>

              {test && (
                <div className="mt-4 space-y-3">
                  <p className="text-sm text-ink-700 dark:text-ink-200">
                    Read <strong>{test.row_count}</strong> payments totalling{" "}
                    <strong>{formatINR(test.total)}</strong>
                    {test.stated_total !== null &&
                      ` — the file's own control total says ${formatINR(test.stated_total)}`}
                    {test.skipped_by_filter > 0 &&
                      `, with ${test.skipped_by_filter} row(s) dropped by the filter`}
                    .
                  </p>
                  {test.problems.map((problem) => (
                    <p
                      key={problem}
                      className="text-xs text-warning-700 dark:text-warning-300"
                    >
                      {problem}
                    </p>
                  ))}
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-ink-200 text-left text-[10px] uppercase tracking-wide text-ink-400 dark:border-ink-700">
                          <th className="py-1.5 pr-3 font-semibold">Code</th>
                          <th className="py-1.5 pr-3 font-semibold">Name</th>
                          <th className="py-1.5 pr-3 font-semibold">Account</th>
                          <th className="py-1.5 text-right font-semibold">Amount</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-ink-200/60 dark:divide-ink-700/50">
                        {test.rows.map((row) => (
                          <tr key={row.row_number}>
                            <td className="py-1.5 pr-3 text-ink-800 dark:text-ink-100">
                              {row.employee_id ?? (
                                <span className="text-danger-600">not mapped</span>
                              )}
                            </td>
                            <td className="py-1.5 pr-3 text-ink-600 dark:text-ink-300">
                              {row.employee_name ?? "—"}
                            </td>
                            <td className="py-1.5 pr-3 text-ink-600 dark:text-ink-300">
                              {row.account_number ?? "—"}
                            </td>
                            <td className="py-1.5 text-right tabular-nums text-ink-900 dark:text-white">
                              {formatINR(row.amount)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {test.truncated && (
                    <p className="text-[11px] text-ink-500 dark:text-ink-400">
                      Showing the first 25 rows.
                    </p>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
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
    <Menu label={label} summary={current?.label ?? value} width="w-80">
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
