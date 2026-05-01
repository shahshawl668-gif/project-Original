import { apiJson } from "@/lib/api";

export type AdminUserRow = {
  id: string;
  email: string;
  company_name: string | null;
  role: string;
  created_at: string;
};

export async function listAdminUsers(): Promise<AdminUserRow[]> {
  return apiJson<AdminUserRow[]>("/api/admin/users");
}

export async function patchUserRole(
  userId: string,
  role: "admin" | "user"
): Promise<AdminUserRow> {
  return apiJson<AdminUserRow>(`/api/admin/users/${userId}/role`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}
