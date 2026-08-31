import { useEffect, useState } from "react";
import { listRuns, RunSummary } from "../api/client";
import { AlertTriangle, Users, CheckCircle, Clock } from "lucide-react";

type StatCard = {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  color: "red" | "orange" | "green" | "blue";
};

export default function Dashboard() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const data = await listRuns();
        setRuns(data.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()));
      } catch (err) {
        console.error("Failed to load runs:", err);
      } finally {
        setLoading(false);
      }
    };
    load();
    const interval = setInterval(load, 5000);
    return () => clearInterval(interval);
  }, []);

  const latestCompleted = runs.find((r) => r.status === "completed");
  const stats: StatCard[] = [
    {
      label: "Total Runs",
      value: runs.length,
      icon: <Clock className="w-5 h-5" />,
      color: "blue",
    },
    {
      label: "Completed",
      value: runs.filter((r) => r.status === "completed").length,
      icon: <CheckCircle className="w-5 h-5" />,
      color: "green",
    },
    {
      label: "Critical Issues (Latest)",
      value: latestCompleted?.summary?.critical || 0,
      icon: <AlertTriangle className="w-5 h-5" />,
      color: latestCompleted?.summary?.critical ? "red" : "green",
    },
    {
      label: "Employees (Latest)",
      value: latestCompleted?.summary?.total_employees || 0,
      icon: <Users className="w-5 h-5" />,
      color: "blue",
    },
  ];

  const colorMap = {
    red: "bg-red-500/10 border-red-500/30 text-red-400",
    orange: "bg-orange-500/10 border-orange-500/30 text-orange-400",
    green: "bg-green-500/10 border-green-500/30 text-green-400",
    blue: "bg-blue-500/10 border-blue-500/30 text-blue-400",
  };

  return (
    <div className="p-8 space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-white mb-2">Payroll Audit Dashboard</h1>
        <p className="text-slate-400">Real-time statutory compliance monitoring for Indian payroll</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((stat, i) => (
          <div key={i} className={`p-4 rounded-lg border ${colorMap[stat.color]} space-y-2`}>
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{stat.label}</span>
              {stat.icon}
            </div>
            <div className="text-2xl font-bold">{stat.value}</div>
          </div>
        ))}
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-lg p-6">
        <h2 className="text-lg font-bold text-white mb-4">Recent Validation Runs</h2>
        {loading ? (
          <div className="text-slate-400 text-center py-8">Loading...</div>
        ) : runs.length === 0 ? (
          <div className="text-slate-400 text-center py-8">No validation runs yet. Upload files to get started.</div>
        ) : (
          <div className="space-y-3">
            {runs.slice(0, 5).map((run) => (
              <div key={run.run_id} className="flex items-center justify-between p-3 bg-slate-800 rounded hover:bg-slate-750 transition">
                <div className="flex-1">
                  <div className="font-mono text-sm text-slate-300">{run.company_id}</div>
                  <div className="text-xs text-slate-500">{run.payroll_month}/{run.payroll_year}</div>
                </div>
                <div className="flex items-center gap-4">
                  {run.summary && (
                    <div className="text-right text-sm">
                      <div className="text-slate-300">{run.summary.total_employees} employees</div>
                      <div className="text-red-400 font-mono">{run.summary.total_issues} issues</div>
                    </div>
                  )}
                  <div
                    className={`px-3 py-1 rounded text-xs font-mono ${
                      run.status === "completed"
                        ? "bg-green-500/20 text-green-400"
                        : run.status === "running"
                          ? "bg-blue-500/20 text-blue-400"
                          : "bg-slate-700 text-slate-400"
                    }`}
                  >
                    {run.status}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-6">
          <h3 className="text-lg font-bold text-white mb-4">Quick Start</h3>
          <ol className="space-y-3 text-sm text-slate-300">
            <li>1. Navigate to <span className="text-orange-400 font-mono">Upload & Validate</span></li>
            <li>2. Upload current payroll register (Excel/CSV)</li>
            <li>3. Optionally attach employee master, CTC, attendance, bank files</li>
            <li>4. Click <span className="text-green-400 font-mono">Validate</span> and wait for report</li>
            <li>5. Download Excel audit report with all exception details</li>
          </ol>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-6">
          <h3 className="text-lg font-bold text-white mb-4">What We Validate</h3>
          <ul className="space-y-2 text-sm text-slate-300">
            <li className="flex gap-2"><span className="text-green-400">✓</span> PF/EPS/VPF calculations & continuity</li>
            <li className="flex gap-2"><span className="text-green-400">✓</span> ESI threshold & wage ceiling rules</li>
            <li className="flex gap-2"><span className="text-green-400">✓</span> Professional Tax (state-wise slabs)</li>
            <li className="flex gap-2"><span className="text-green-400">✓</span> Minimum Wage compliance</li>
            <li className="flex gap-2"><span className="text-green-400">✓</span> TDS old/new regime calculations</li>
            <li className="flex gap-2"><span className="text-green-400">✓</span> Proration, Arrears, FNF Settlement</li>
            <li className="flex gap-2"><span className="text-green-400">✓</span> Bank & Attendance reconciliation</li>
            <li className="flex gap-2"><span className="text-green-400">✓</span> Statistical anomaly detection</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
