import { apiFetch, parseEnvelopeResponse } from "@/lib/api";

/**
 * The employee master: who works here, when they joined or left, where they
 * work. Validation uses it to catch people paid before joining or after
 * leaving, people missing from the master, and state-wise PT/LWF.
 *
 * `previewMaster` reads a file and reports how it was understood without
 * storing anything; `commitMaster` stores it as the version effective from a
 * month. Sending the same effective month again replaces that version.
 */

export type MasterPreview = {
  row_count: number;
  header_map: Record<string, string>;
  unmapped_columns: string[];
  warnings: string[];
  sample: Record<string, string | number | null>[];
};

export type MasterUpload = {
  id: string;
  effective_from: string;
  filename: string | null;
  employee_count: number | null;
  created_at: string | null;
  counts?: { created: number; updated: number; unchanged: number; removed: number };
  duplicates_skipped?: string[];
};

export const MASTER_TEMPLATE =
  "Employee ID,Employee Name,Date of Joining,Date of Exit,Gender,State,Department,Employment Type,UAN,ESIC IP Number\r\n" +
  "E001,Asha Menon,2022-06-15,,Female,Karnataka,Finance,Permanent,101202600001,3100000001\r\n";

function form(file: File, meta?: object) {
  const body = new FormData();
  body.append("file", file);
  if (meta) body.append("meta", JSON.stringify(meta));
  return body;
}

export function previewMaster(file: File) {
  return apiFetch("/api/workforce/master/upload", { method: "POST", body: form(file, {}) }).then((r) =>
    parseEnvelopeResponse<MasterPreview>(r),
  );
}

export function commitMaster(file: File, effectiveFrom: string) {
  return apiFetch("/api/workforce/master/commit", {
    method: "POST",
    body: form(file, { effective_from: `${effectiveFrom}-01` }),
  }).then((r) => parseEnvelopeResponse<MasterUpload>(r));
}

export function fetchMasterUploads() {
  return apiFetch("/api/workforce/master/uploads").then((r) => parseEnvelopeResponse<MasterUpload[]>(r));
}
