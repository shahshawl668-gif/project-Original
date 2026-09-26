"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { apiFetch, parseEnvelopeResponse, setTokens } from "@/lib/api";

type Workspace = { id: string; name: string; slug: string; login_path: string; invitation_path?: string };
type SupportOrg = { id: string; name: string; support_access_policy: string };
type Staff = { id: string; email: string; role: string };

export default function PlatformPage() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const [rows, setRows] = useState<Workspace[]>([]);
  const [supportOrgs, setSupportOrgs] = useState<SupportOrg[]>([]);
  const [supportOrgId, setSupportOrgId] = useState("");
  const [reason, setReason] = useState("");
  const [supportMessage, setSupportMessage] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [invitation, setInvitation] = useState("");
  const [staffEmail, setStaffEmail] = useState("");
  const [staffRole, setStaffRole] = useState("support");
  const [staffInvitation, setStaffInvitation] = useState("");
  const [staff, setStaff] = useState<Staff[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace("/platform/login");
    if (user) {
      if (user.platform_role !== "support") void apiFetch("/api/admin/organizations").then(parseEnvelopeResponse<Workspace[]>).then(setRows).catch((e) => setError(String(e)));
      void apiFetch("/api/admin/support/organizations").then(parseEnvelopeResponse<SupportOrg[]>).then(setSupportOrgs).catch((e) => setError(String(e)));
      if (user.platform_role === "owner") void apiFetch("/api/admin/staff").then(parseEnvelopeResponse<Staff[]>).then(setStaff).catch((e) => setError(String(e)));
    }
  }, [user, loading, router]);

  async function create(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true); setError("");
    try {
      const response = await apiFetch("/api/admin/organizations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, owner_email: email }) });
      const created = await parseEnvelopeResponse<Workspace>(response);
      setRows((previous) => [created, ...previous]);
      setInvitation(`${window.location.origin}${created.invitation_path}`);
      setName(""); setEmail("");
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to create workspace"); }
    finally { setBusy(false); }
  }

  async function inviteStaff(e: FormEvent) {
    e.preventDefault(); setError("");
    try {
      const response = await apiFetch("/api/admin/staff/invitations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: staffEmail, role: staffRole }) });
      const result = await parseEnvelopeResponse<{ invitation_path: string }>(response);
      setStaffInvitation(`${window.location.origin}${result.invitation_path}`);
      setStaffEmail("");
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to invite staff"); }
  }

  async function revokeStaff(member: Staff) {
    try {
      const response = await apiFetch(`/api/admin/staff/${member.id}/role`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role: "none" }) });
      await parseEnvelopeResponse(response);
      setStaff((current) => current.filter((item) => item.id !== member.id));
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to revoke access"); }
  }

  async function openSupport(e: FormEvent) {
    e.preventDefault(); setError(""); setSupportMessage("");
    try {
      const response = await apiFetch("/api/admin/support/grants", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ org_id: supportOrgId, reason, minutes: 30 }) });
      const grant = await parseEnvelopeResponse<{ state: string }>(response);
      if (grant.state !== "active") { setSupportMessage("Access requested. The client owner must approve it before you can enter."); return; }
      const session = await apiFetch("/api/auth/support-session", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ org_id: supportOrgId }) });
      const tokens = await parseEnvelopeResponse<{ access_token: string; refresh_token: string }>(session);
      setTokens(tokens.access_token, tokens.refresh_token);
      window.location.assign("/dashboard");
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to open support session"); }
  }

  if (loading || !user) return <main className="p-8">Checking platform session…</main>;
  return <main className="mx-auto max-w-4xl space-y-8 p-6 text-ink-900">
    <header className="flex items-center justify-between"><h1 className="text-2xl font-bold">Peopleopslab platform</h1><button onClick={() => void logout().then(() => router.push("/platform/login"))}>Sign out</button></header>
    {user.platform_role !== "support" && <section className="rounded-xl border p-6"><h2 className="mb-4 text-lg font-semibold">Create client workspace</h2>
      <form onSubmit={create} className="grid gap-3 sm:grid-cols-3"><input className="rounded border p-3" required placeholder="Company name" value={name} onChange={(e) => setName(e.target.value)} /><input className="rounded border p-3" type="email" required placeholder="Owner email" value={email} onChange={(e) => setEmail(e.target.value)} /><button className="rounded bg-sky-700 p-3 text-white disabled:opacity-50" disabled={busy}>{busy ? "Creating…" : "Create and invite"}</button></form>
      {error && <p role="alert" className="mt-3 text-red-700">{error}</p>}
      {invitation && <p className="mt-4 break-all">Share this one-time invitation with the client owner: <a className="text-sky-700 underline" href={invitation}>{invitation}</a></p>}
    </section>}
    {user.platform_role === "owner" && <section className="rounded-xl border p-6"><h2 className="mb-4 text-lg font-semibold">Invite platform staff</h2>
      <form onSubmit={inviteStaff} className="flex flex-wrap gap-3"><input className="rounded border p-3" type="email" required placeholder="Team member email" value={staffEmail} onChange={(e) => setStaffEmail(e.target.value)} /><select className="rounded border p-3" value={staffRole} onChange={(e) => setStaffRole(e.target.value)}><option value="support">Support</option><option value="admin">Platform admin</option></select><button className="rounded bg-sky-700 p-3 text-white">Create invitation</button></form>
      {staffInvitation && <p className="mt-3 break-all">Share this one-time staff invitation: <a className="text-sky-700 underline" href={staffInvitation}>{staffInvitation}</a></p>}
      <ul className="mt-4 space-y-2">{staff.map((member) => <li key={member.id} className="flex items-center justify-between rounded border p-3"><span>{member.email} · {member.role}</span>{member.role !== "owner" && <button className="text-red-700 underline" onClick={() => void revokeStaff(member)}>Revoke access</button>}</li>)}</ul>
    </section>}
    <section className="rounded-xl border p-6"><h2 className="mb-3 text-lg font-semibold">Client support</h2><p className="mb-4 text-sm">Access is time limited, read only, masked, and recorded for the client.</p><form onSubmit={openSupport} className="space-y-3"><select required className="w-full rounded border p-3" value={supportOrgId} onChange={(e) => setSupportOrgId(e.target.value)}><option value="">Select client</option>{supportOrgs.map((org) => <option key={org.id} value={org.id}>{org.name} ({org.support_access_policy})</option>)}</select><textarea required minLength={12} className="w-full rounded border p-3" placeholder="Reason for access (visible to the client)" value={reason} onChange={(e) => setReason(e.target.value)} /><button className="rounded bg-sky-700 px-5 py-3 text-white">Request support access</button></form>{supportMessage && <p className="mt-3">{supportMessage}</p>}</section>
    {user.platform_role !== "support" && <section><h2 className="mb-3 text-lg font-semibold">Client workspaces</h2><ul className="space-y-2">{rows.map((row) => <li key={row.id} className="rounded border p-4"><strong>{row.name}</strong><span className="ml-3 text-sm text-ink-500">{row.slug}</span><p className="mt-1 text-sm">Login: <a className="text-sky-700 underline" href={row.login_path}>{window.location.origin}{row.login_path}</a></p></li>)}</ul></section>}
  </main>;
}
