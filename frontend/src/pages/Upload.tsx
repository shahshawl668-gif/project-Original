"use client";

import { useState } from "react";
import { uploadFiles, triggerValidation } from "../api/client";
import { Upload, AlertCircle, Check, Loader } from "lucide-react";
import { useRouter } from "next/navigation";

export default function UploadPage() {
  const [files, setFiles] = useState<Record<string, File | null>>({
    current_payroll: null,
    previous_payroll: null,
    employee_master: null,
    ctc_master: null,
    attendance: null,
    leave: null,
    bank_file: null,
  });

  const [payrollMonth, setPayrollMonth] = useState(new Date().getMonth() + 1);
  const [payrollYear, setPayrollYear] = useState(new Date().getFullYear());
  const [companyId, setCompanyId] = useState("DEFAULT");
  const [uploading, setUploading] = useState(false);
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  const fileSpecs: Record<string, { label: string; required: boolean; description: string }> = {
    current_payroll: {
      label: "Current Payroll Register",
      required: true,
      description: "Employee ID, Name, Gross, Deductions (PF, ESI, PT, TDS, LWF, etc.)",
    },
    previous_payroll: {
      label: "Previous Payroll Register",
      required: false,
      description: "For month-on-month variance & anomaly detection",
    },
    employee_master: {
      label: "Employee Master",
      required: false,
      description: "DOJ, Skill Category, State, Bank Account, International Worker flag",
    },
    ctc_master: {
      label: "CTC Master",
      required: false,
      description: "Annual CTC for reconciliation with payroll",
    },
    attendance: {
      label: "Attendance Dump",
      required: false,
      description: "Payable days, LOP days from attendance system",
    },
    leave: {
      label: "Leave Dump",
      required: false,
      description: "Leave balances, LOP leaves for reconciliation",
    },
    bank_file: {
      label: "Bank File",
      required: false,
      description: "Employee ID, Net Pay for bank reconciliation",
    },
  };

  const handleFileChange = (field: string, file: File | null) => {
    setFiles((prev) => ({ ...prev, [field]: file }));
    setError(null);
  };

  const handleDragDrop = (e: React.DragEvent, field: string) => {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file && (file.name.endsWith(".xlsx") || file.name.endsWith(".csv") || file.name.endsWith(".xls"))) {
      handleFileChange(field, file);
    } else {
      setError("Only Excel (.xlsx, .xls) and CSV files are supported");
    }
  };

  const validateForm = () => {
    if (!files.current_payroll) {
      setError("Current payroll register is required");
      return false;
    }
    if (payrollMonth < 1 || payrollMonth > 12) {
      setError("Invalid payroll month (1-12)");
      return false;
    }
    return true;
  };

  const handleUpload = async () => {
    if (!validateForm()) return;

    setUploading(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append("payroll_month", payrollMonth.toString());
      formData.append("payroll_year", payrollYear.toString());
      formData.append("company_id", companyId);

      Object.entries(files).forEach(([key, file]) => {
        if (file) {
          formData.append(key, file);
        }
      });

      const { run_id } = await uploadFiles(formData);

      setValidating(true);
      await triggerValidation(run_id);
      router.push(`/validations/${run_id}`);
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } }; message?: string };
      setError(axiosErr.response?.data?.detail || axiosErr.message || "Upload failed");
      setValidating(false);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-white mb-2">Upload & Validate Payroll</h1>
        <p className="text-slate-400">Upload your payroll files to begin statutory compliance audit</p>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 flex gap-3 text-red-400">
          <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
          <p>{error}</p>
        </div>
      )}

      <div className="space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">Payroll Month *</label>
            <select
              value={payrollMonth}
              onChange={(e) => setPayrollMonth(parseInt(e.target.value))}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-slate-100 text-sm"
            >
              {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
                <option key={m} value={m}>
                  {new Date(2024, m - 1).toLocaleDateString("en-US", { month: "long" })}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">Payroll Year *</label>
            <input
              type="number"
              min="2020"
              max="2100"
              value={payrollYear}
              onChange={(e) => setPayrollYear(parseInt(e.target.value))}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-slate-100 text-sm"
            />
          </div>
          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-slate-300 mb-2">Company ID</label>
            <input
              type="text"
              value={companyId}
              onChange={(e) => setCompanyId(e.target.value)}
              placeholder="e.g., ACME-001"
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded text-slate-100 text-sm"
            />
          </div>
        </div>

        {Object.entries(fileSpecs).map(([key, spec]) => (
          <div
            key={key}
            className="border-2 border-dashed border-slate-700 rounded-lg p-6 bg-slate-900/50 hover:border-slate-600 transition cursor-pointer"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => handleDragDrop(e, key)}
            onClick={() => document.getElementById(`file-${key}`)?.click()}
          >
            <input
              id={`file-${key}`}
              type="file"
              accept=".xlsx,.xls,.csv"
              className="hidden"
              onChange={(e) => handleFileChange(key, e.target.files?.[0] || null)}
            />
            <div className="space-y-2">
              <div className="flex items-center gap-3">
                {files[key] ? <Check className="w-5 h-5 text-green-400" /> : <Upload className="w-5 h-5 text-slate-400" />}
                <div>
                  <p className="font-medium text-slate-100">
                    {spec.label}
                    {spec.required && <span className="text-red-400"> *</span>}
                  </p>
                  <p className="text-xs text-slate-500">{spec.description}</p>
                </div>
              </div>
              {files[key] && <p className="text-xs text-green-400 ml-8">✓ {files[key]!.name}</p>}
            </div>
          </div>
        ))}
      </div>

      <div className="flex gap-4">
        <button
          onClick={handleUpload}
          disabled={uploading || validating}
          className="flex-1 px-6 py-3 bg-orange-500 hover:bg-orange-600 disabled:bg-slate-700 disabled:cursor-not-allowed text-white font-medium rounded transition flex items-center justify-center gap-2"
        >
          {uploading || validating ? <Loader className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
          {uploading ? "Uploading..." : validating ? "Validating..." : "Upload & Validate"}
        </button>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-lg p-6">
        <h3 className="font-bold text-white mb-3">File Format Requirements</h3>
        <ul className="text-sm text-slate-300 space-y-2">
          <li>• <strong>Excel/CSV</strong>: Must contain Employee_ID or employee_code column</li>
          <li>• <strong>Column Names</strong>: Automatically normalized (e.g., &quot;Emp_ID&quot; → &quot;Employee_ID&quot;)</li>
          <li>• <strong>Numeric Columns</strong>: Salary, PF, ESI, TDS, PT, LWF automatically detected</li>
          <li>• <strong>Date Columns</strong>: Automatically parsed (dd/mm/yyyy or mm/dd/yyyy)</li>
          <li>• <strong>Max File Size</strong>: 50 MB per file</li>
        </ul>
      </div>
    </div>
  );
}
