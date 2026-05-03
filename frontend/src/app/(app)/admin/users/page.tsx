"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { Shield, Loader2, Lock, Users } from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/context/AuthContext";
import { AdminUserRow, listAdminUsers, patchUserRole } from "@/lib/admin";
import { refreshSession } from "@/lib/api";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";

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
      <div className="space-y-6">
        <PageHeader
          eyebrow="Restricted"
          title="Admin only"
          description="You need an administrator account to manage tenant users."
        />
        <Card>
          <EmptyState
            icon={Lock}
            title="Permission required"
            description="Sign in as an administrator to manage roles for your tenant."
            action={
              <Link href="/dashboard">
                <Button variant="outline" size="sm">
                  Back to dashboard
                </Button>
              </Link>
            }
          />
        </Card>
      </div>
    );
  }

  const rows = q.data ?? [];

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Administration"
        title={
          <span className="inline-flex items-center gap-3">
            <Shield className="text-brand-600 dark:text-brand-300" size={26} />
            Users & roles
          </span>
        }
        description="Promote or demote human accounts. The built-in system user is never listed."
      />

      {q.isLoading && (
        <div className="flex items-center gap-2 text-sm text-ink-500 dark:text-ink-400">
          <Loader2 className="animate-spin" size={16} /> Loading users…
        </div>
      )}
      {q.isError && (
        <AlertBanner variant="error" title="Could not load users">
          {(q.error as Error).message}
        </AlertBanner>
      )}

      <Card className="overflow-hidden">
        {!q.isLoading && rows.length === 0 ? (
          <EmptyState
            icon={Users}
            title="No registered users"
            description="When teammates sign up to your tenant, they will appear here."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="bg-ink-50/80 text-left text-[11px] font-bold uppercase tracking-[0.12em] text-ink-500 dark:bg-white/[0.03] dark:text-ink-300">
                  <th className="px-4 py-3">Email</th>
                  <th className="px-4 py-3">Company</th>
                  <th className="px-4 py-3">Role</th>
                  <th className="w-56 px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100 dark:divide-white/[0.05]">
                {rows.map((r: AdminUserRow) => (
                  <tr
                    key={r.id}
                    className="transition-colors hover:bg-ink-50/60 dark:hover:bg-white/[0.04]"
                  >
                    <td className="px-4 py-3 font-mono text-xs text-ink-900 dark:text-white">
                      {r.email}
                    </td>
                    <td className="px-4 py-3 text-ink-600 dark:text-ink-300">
                      {r.company_name ?? "—"}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={r.role === "admin" ? "primary" : "secondary"}>
                        {r.role}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex flex-wrap justify-end gap-2">
                        {r.role !== "admin" && (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            disabled={mut.isPending}
                            onClick={() => mut.mutate({ id: r.id, role: "admin" })}
                          >
                            Make admin
                          </Button>
                        )}
                        {r.role === "admin" && (
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            disabled={mut.isPending}
                            onClick={() => mut.mutate({ id: r.id, role: "user" })}
                          >
                            Remove admin
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <p className="text-xs text-ink-500 dark:text-ink-400">
        You cannot remove the last admin. Protects against accidental lock-out (demote yourself last only after
        promoting another admin).
      </p>
    </div>
  );
}
