"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { getRun, getIssues, downloadReport, ValidationIssue, RunSummary } from "../api/client";
import { Loader, Download, Filter, CheckCircle } from "lucide-react";

export default function Reports() {
  const params = useParams<{ runId: string }>();
  const runId = params?.runId;
  const [run, setRun] = useState<RunSummary | null>(null);
  const [issues, setIssues] = useState<ValidationIssue[]>([]);
  const [severityFilter, setSeverityFilter] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!runId) return;

    let cancelled = false;
    let interval: ReturnType<typeof setInterval> | null = null;

    const load = async () => {
      try {
        const [runData, issuesData] = await Promise.all([
          getRun(runId),
          getIssues(runId, severityFilter || undefined),
        ]);
        if (cancelled) return;
        setRun(runData);
        setIssues(issuesData.issues);
        if (runData.status === "running" && !interval) {
          interval = setInterval(load, 2000);
        }
        if (runData.status !== "running" && interval) {
          clearInterval(interval);
          interval = null;
        }
      } catch (err) {
        console.error("Failed to load report:", err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
    };
  }, [runId, severityFilter]);

  if (loading || !run) {
    return (
      <div className="flex items-center justify-center h-screen">
        <Loader className="w-8 h-8 text-orange-500 animate-spin" />
      </div>
    );
  }

  const summary = run.summary || {
    total_employees: 0,
    total_issues: 0,
    critical: 0,
    high: 0,
    medium: 0,
    low: 0,
  };
  const severity: Record<string, { label: string; color: string; count: number }> = {
    CRITICAL: { label: "Critical", color: "text-red-400", count: summary.critical || 0 },
    HIGH: { label: "High", color: "text-orange-400", count: summary.high || 0 },
    MEDIUM: { label: "Medium", color: "text-yellow-400", count: summary.medium || 0 },
    LOW: { label: "Low", color: "text-green-400", count: summary.low || 0 },
  };

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white">Validation Report</h1>
          <p className="text-slate-400 mt-1">
            {run.company_id} | Payroll {run.payroll_month}/{run.payroll_year}
          </p>
        </div>
        {run.status === "completed" && (
          <button
            onClick={() => runId && downloadReport(runId)}
            className="px-6 py-2 bg-orange-500 hover:bg-orange-600 text-white font-medium rounded flex items-center gap-2 transition"
          >
            <Download className="w-4 h-4" />
            Download Excel Report
          </button>
        )}
      </div>

      {run.status === "running" && (
        <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4 flex gap-3 text-blue-400">
          <Loader className="w-5 h-5 animate-spin flex-shrink-0" />
          <p>Validation in progress...</p>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
          <p className="text-sm text-slate-400">Total Employees</p>
          <p className="text-2xl font-bold text-white">{summary.total_employees}</p>
        </div>
        {Object.entries(severity).map(([sev, { label, color, count }]) => (
          <div
            key={sev}
            className="bg-slate-900 border border-slate-800 rounded-lg p-4 cursor-pointer hover:border-slate-700 transition"
            onClick={() => setSeverityFilter(sev)}
          >
            <p className="text-sm text-slate-400">{label} Issues</p>
            <p className={`text-2xl font-bold ${color}`}>{count}</p>
          </div>
        ))}
      </div>

      {issues.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
          <div className="p-6 border-b border-slate-800 flex items-center justify-between">
            <h2 className="text-lg font-bold text-white">Exception Details ({issues.length})</h2>
            <div className="flex items-center gap-2">
              <Filter className="w-4 h-4 text-slate-400" />
              <select
                value={severityFilter || ""}
                onChange={(e) => setSeverityFilter(e.target.value || null)}
                className="px-3 py-1 bg-slate-800 border border-slate-700 rounded text-sm text-slate-100"
              >
                <option value="">All Severities</option>
                <option value="CRITICAL">Critical Only</option>
                <option value="HIGH">High & Above</option>
                <option value="MEDIUM">Medium & Above</option>
              </select>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-800 sticky top-0">
                <tr>
                  <th className="px-6 py-3 text-left font-mono text-xs uppercase tracking-wider text-slate-400">Employee</th>
                  <th className="px-6 py-3 text-left font-mono text-xs uppercase tracking-wider text-slate-400">Issue</th>
                  <th className="px-6 py-3 text-left font-mono text-xs uppercase tracking-wider text-slate-400">Component</th>
                  <th className="px-6 py-3 text-left font-mono text-xs uppercase tracking-wider text-slate-400">Expected</th>
                  <th className="px-6 py-3 text-left font-mono text-xs uppercase tracking-wider text-slate-400">Actual</th>
                  <th className="px-6 py-3 text-left font-mono text-xs uppercase tracking-wider text-slate-400">Variance</th>
                  <th className="px-6 py-3 text-left font-mono text-xs uppercase tracking-wider text-slate-400">Severity</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {issues.map((issue, i) => (
                  <tr key={i} className="hover:bg-slate-800/50 transition">
                    <td className="px-6 py-4 text-slate-300">{issue.employee_name}</td>
                    <td className="px-6 py-4">
                      <code className="text-xs bg-slate-800 px-2 py-1 rounded text-slate-300">{issue.flag}</code>
                    </td>
                    <td className="px-6 py-4 text-slate-400 text-xs">{issue.component || "-"}</td>
                    <td className="px-6 py-4 text-slate-300 font-mono">
                      {typeof issue.expected_value === "number" ? `₹${issue.expected_value.toFixed(2)}` : "-"}
                    </td>
                    <td className="px-6 py-4 text-slate-300 font-mono">
                      {typeof issue.actual_value === "number" ? `₹${issue.actual_value.toFixed(2)}` : "-"}
                    </td>
                    <td className={`px-6 py-4 font-mono ${issue.difference && issue.difference !== 0 ? "text-red-400" : "text-green-400"}`}>
                      {issue.difference ? `₹${issue.difference.toFixed(2)}` : "-"}
                    </td>
                    <td className="px-6 py-4">
                      <span
                        className={`px-2 py-1 rounded text-xs font-mono font-bold ${
                          issue.severity === "CRITICAL"
                            ? "bg-red-500/20 text-red-400"
                            : issue.severity === "HIGH"
                              ? "bg-orange-500/20 text-orange-400"
                              : issue.severity === "MEDIUM"
                                ? "bg-yellow-500/20 text-yellow-400"
                                : "bg-green-500/20 text-green-400"
                        }`}
                      >
                        {issue.severity}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {issues.length === 0 && run.status === "completed" && (
        <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-8 text-center">
          <CheckCircle className="w-12 h-12 text-green-400 mx-auto mb-4" />
          <h3 className="text-lg font-bold text-green-400 mb-2">All Validations Passed!</h3>
          <p className="text-slate-400">No statutory compliance issues detected.</p>
        </div>
      )}
    </div>
  );
}
