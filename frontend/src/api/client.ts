import axios from "axios";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: 120000,
});

export type RunSummary = {
  run_id: string;
  company_id: string;
  status: "uploaded" | "running" | "completed" | "failed";
  created_at: string;
  completed_at?: string;
  payroll_month?: number;
  payroll_year?: number;
  summary?: {
    total_employees: number;
    total_issues: number;
    critical: number;
    high: number;
    medium: number;
    low: number;
  };
};

export type ValidationIssue = {
  employee_id: string;
  employee_name: string;
  flag: string;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
  description: string;
  expected_value?: number;
  actual_value?: number;
  difference?: number;
  component?: string;
};

export const uploadFiles = async (formData: FormData): Promise<{ run_id: string }> => {
  const { data } = await apiClient.post("/api/v1/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
};

export const triggerValidation = async (runId: string) => {
  const { data } = await apiClient.post(`/api/v1/validate/${runId}`);
  return data;
};

export const getRun = async (runId: string): Promise<RunSummary> => {
  const { data } = await apiClient.get(`/api/v1/runs/${runId}`);
  return data;
};

export const listRuns = async (): Promise<RunSummary[]> => {
  const { data } = await apiClient.get("/api/v1/runs");
  return data;
};

export const getIssues = async (runId: string, severity?: string): Promise<{ issues: ValidationIssue[]; total: number }> => {
  const params = severity ? { severity } : {};
  const { data } = await apiClient.get(`/api/v1/runs/${runId}/issues`, { params });
  return data;
};

export const downloadReport = (runId: string) => {
  window.open(`${BASE_URL}/api/v1/runs/${runId}/report`, "_blank");
};
