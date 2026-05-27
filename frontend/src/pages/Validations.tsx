"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { listRuns, RunSummary } from "../api/client";
import { Loader, ArrowRight, AlertTriangle } from "lucide-react";

export default function Validations() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const data = await listRuns();
        if (cancelled) return;
        setRuns(
          data.sort(
            (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
          ),
        );
      } catch (err) {
        console.error("Failed to load runs:", err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    const interval = setInterval(load, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const getStatusBadgeColor = (status: string) => {
    switch (status) {
      case "completed":
        return "bg-green-500/20 text-green-400";
      case "running":
        return "bg-blue-500/20 text-blue-400";
      case "failed":
        return "bg-red-500/20 text-red-400";
      default:
        return "bg-slate-700 text-slate-400";
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <Loader className="w-8 h-8 text-orange-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white">Validation Runs</h1>
          <p className="text-slate-400 mt-1">All payroll audits and compliance checks</p>
        </div>
        <button
          onClick={() => router.push("/upload")}
          className="px-6 py-2 bg-orange-500 hover:bg-orange-600 text-white font-medium rounded transition"
        >
          New Validation
        </button>
      </div>

      {runs.length === 0 ? (
        <div className="text-center py-12">
          <AlertTriangle className="w-12 h-12 text-slate-600 mx-auto mb-4" />
          <p className="text-slate-400 mb-4">No validation runs yet</p>
          <button
            onClick={() => router.push("/upload")}
            className="px-6 py-2 bg-orange-500 hover:bg-orange-600 text-white font-medium rounded transition"
          >
            Get Started
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {runs.map((run) => (
            <div
              key={run.run_id}
              className="bg-slate-900 border border-slate-800 rounded-lg p-6 hover:border-slate-700 transition cursor-pointer"
              onClick={() => router.push(`/validations/${run.run_id}`)}
            >
              <div className="flex items-start justify-between gap-6">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <h3 className="font-mono text-white">{run.company_id}</h3>
                    <span className={`px-2 py-1 rounded text-xs font-mono ${getStatusBadgeColor(run.status)}`}>
                      {run.status.toUpperCase()}
                    </span>
                  </div>
                  <div className="text-sm text-slate-400 grid grid-cols-4 gap-4">
                    <div>
                      <p className="text-xs uppercase tracking-wider text-slate-500">Payroll</p>
                      <p className="font-mono text-slate-300">
                        {run.payroll_month}/{run.payroll_year}
                      </p>
                    </div>
                    {run.summary && (
                      <>
                        <div>
                          <p className="text-xs uppercase tracking-wider text-slate-500">Employees</p>
                          <p className="font-mono text-slate-300">{run.summary.total_employees}</p>
                        </div>
                        <div>
                          <p className="text-xs uppercase tracking-wider text-slate-500">Total Issues</p>
                          <p className={`font-mono ${run.summary.total_issues > 0 ? "text-red-400" : "text-green-400"}`}>
                            {run.summary.total_issues}
                          </p>
                        </div>
                        <div>
                          <p className="text-xs uppercase tracking-wider text-slate-500">Compliance</p>
                          <p className="font-mono text-orange-400">
                            {run.summary.total_employees > 0
                              ? Math.round(
                                  ((run.summary.total_employees - run.summary.total_issues / 2) /
                                    run.summary.total_employees) *
                                    100,
                                )
                              : 0}
                            %
                          </p>
                        </div>
                      </>
                    )}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-xs text-slate-500 mb-3">
                    {new Date(run.created_at).toLocaleDateString()} {new Date(run.created_at).toLocaleTimeString()}
                  </div>
                  <ArrowRight className="w-5 h-5 text-slate-600" />
                </div>
              </div>

              {run.summary && run.summary.critical > 0 && (
                <div className="mt-4 pt-4 border-t border-slate-800 flex gap-6 text-sm">
                  {run.summary.critical > 0 && (
                    <div className="flex items-center gap-2 text-red-400">
                      <AlertTriangle className="w-4 h-4" />
                      <span>{run.summary.critical} Critical</span>
                    </div>
                  )}
                  {run.summary.high > 0 && (
                    <div className="flex items-center gap-2 text-orange-400">
                      <AlertTriangle className="w-4 h-4" />
                      <span>{run.summary.high} High</span>
                    </div>
                  )}
                  {run.summary.medium > 0 && (
                    <div className="flex items-center gap-2 text-yellow-400">
                      <AlertTriangle className="w-4 h-4" />
                      <span>{run.summary.medium} Medium</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
