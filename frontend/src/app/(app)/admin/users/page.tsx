"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { Shield, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/context/AuthContext";
import { AdminUserRow, listAdminUsers, patchUserRole } from "@/lib/admin";
import { refreshSession } from "@/lib/api";

export default function AdminUsersPage() {
  const { user, refreshUser } = useAuth();
  const qc = useQueryClient();

  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const q = useQuery({
    queryKey: ["admin-users"],
    queryFn: listAdminUsers,
    enabled: mounted && user?.role === "admin",
  });

  const mut = useMutation({
    mutationFn: ({ id, role }: { id: string; role: "admin" | "user" }) => patchUserRole(id, role),
    onSuccess: async (updated, vars) => {
      toast.success("Role updated");
      await qc.invalidateQueries({ queryKey: ["admin-users"] });
      if (user?.id === vars.id) {
        await refreshSession();
        await refreshUser();
      }
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (user?.role !== "admin") {
    return (
      <div className="max-w-lg space-y-4">
        <h1 className="text-xl font-semibold text-slate-900">Admin only</h1>
        <p className="text-sm text-slate-600">
          You need an administrator account to manage tenant users.
        </p>
        <Link href="/dashboard" className="text-sm text-brand-600 font-medium hover:underline">
          ← Back to dashboard
        </Link>
      </div>
    );
  }

  const rows = q.data ?? [];

  return (
    <div className="max-w-3xl space-y-6">
      <div className="flex items-center gap-2">
        <Shield className="text-brand-600" size={24} />
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Users & roles</h1>
          <p className="text-sm text-slate-600 mt-0.5">
            Promote or demote human accounts. The built-in system user is never listed.
          </p>
        </div>
      </div>

      {q.isLoading && (
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="animate-spin" size={16} /> Loading users…
        </div>
      )}
      {q.isError && (
        <p className="text-sm text-red-600" role="alert">
          {(q.error as Error).message}
        </p>
      )}

      <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-2 font-medium">Email</th>
              <th className="px-4 py-2 font-medium">Company</th>
              <th className="px-4 py-2 font-medium">Role</th>
              <th className="px-4 py-2 font-medium w-56" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((r: AdminUserRow) => (
              <tr key={r.id}>
                <td className="px-4 py-3 font-mono text-xs">{r.email}</td>
                <td className="px-4 py-3 text-slate-600">{r.company_name ?? "—"}</td>
                <td className="px-4 py-3">
                  <span
                    className={`inline-flex text-xs font-semibold px-2 py-0.5 rounded ${
                      r.role === "admin" ? "bg-brand-100 text-brand-800" : "bg-slate-100 text-slate-700"
                    }`}
                  >
                    {r.role}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  <div className="flex gap-2 justify-end flex-wrap">
                    {r.role !== "admin" && (
                      <button
                        type="button"
                        disabled={mut.isPending}
                        className="text-xs rounded-md border border-brand-200 text-brand-700 px-2 py-1 hover:bg-brand-50 disabled:opacity-50"
                        onClick={() => mut.mutate({ id: r.id, role: "admin" })}
                      >
                        Make admin
                      </button>
                    )}
                    {r.role === "admin" && (
                      <button
                        type="button"
                        disabled={mut.isPending}
                        className="text-xs rounded-md border border-slate-200 text-slate-700 px-2 py-1 hover:bg-slate-50 disabled:opacity-50"
                        onClick={() => mut.mutate({ id: r.id, role: "user" })}
                      >
                        Remove admin
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!q.isLoading && rows.length === 0 && (
          <p className="text-sm text-slate-500 p-4">No registered users.</p>
        )}
      </div>

      <p className="text-xs text-slate-400">
        You cannot remove the last admin. Protects against accidental lock-out (demote yourself last only after promoting
        another admin).
      </p>
    </div>
  );
}
