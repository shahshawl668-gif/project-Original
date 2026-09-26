"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import { apiFetch, parseEnvelopeResponse } from "@/lib/api";

type Workspace = { id: string; name: string; slug: string; login_path: string; invitation_path?: string };

export default function PlatformPage() {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const [rows, setRows] = useState<Workspace[]>([]);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [invitation, setInvitation] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace("/platform/login");
    if (user) void apiFetch("/api/admin/organizations").then(parseEnvelopeResponse<Workspace[]>).then(setRows).catch((e) => setError(String(e)));
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

  if (loading || !user) return <main className="p-8">Checking platform session…</main>;
  return <main className="mx-auto max-w-4xl space-y-8 p-6 text-ink-900">
    <header className="flex items-center justify-between"><h1 className="text-2xl font-bold">Peopleopslab platform</h1><button onClick={() => void logout().then(() => router.push("/platform/login"))}>Sign out</button></header>
    <section className="rounded-xl border p-6"><h2 className="mb-4 text-lg font-semibold">Create client workspace</h2>
      <form onSubmit={create} className="grid gap-3 sm:grid-cols-3"><input className="rounded border p-3" required placeholder="Company name" value={name} onChange={(e) => setName(e.target.value)} /><input className="rounded border p-3" type="email" required placeholder="Owner email" value={email} onChange={(e) => setEmail(e.target.value)} /><button className="rounded bg-sky-700 p-3 text-white disabled:opacity-50" disabled={busy}>{busy ? "Creating…" : "Create and invite"}</button></form>
      {error && <p role="alert" className="mt-3 text-red-700">{error}</p>}
      {invitation && <p className="mt-4 break-all">Share this one-time invitation with the client owner: <a className="text-sky-700 underline" href={invitation}>{invitation}</a></p>}
    </section>
    <section><h2 className="mb-3 text-lg font-semibold">Client workspaces</h2><ul className="space-y-2">{rows.map((row) => <li key={row.id} className="rounded border p-4"><strong>{row.name}</strong><span className="ml-3 text-sm text-ink-500">{row.slug}</span><p className="mt-1 text-sm">Login: <a className="text-sky-700 underline" href={row.login_path}>{window.location.origin}{row.login_path}</a></p></li>)}</ul></section>
  </main>;
}
