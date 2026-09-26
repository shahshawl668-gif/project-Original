"use client";

import { Suspense, useState, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";
import { AuthShell } from "@/components/auth/AuthShell";
import { apiFetch, parseEnvelopeResponse, setTokens } from "@/lib/api";

type TokenPair = { access_token: string; refresh_token: string };

function JoinForm() {
  const token = useSearchParams().get("token") || "";
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function join(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const response = await apiFetch("/api/auth/platform-invitations/register", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token, password }) });
      const pair = await parseEnvelopeResponse<TokenPair>(response);
      setTokens(pair.access_token, pair.refresh_token);
      window.location.assign("/platform");
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to accept invitation"); setBusy(false); }
  }
  return <AuthShell><h1 className="text-2xl font-bold">Join the Peopleopslab team</h1><p className="mt-3 text-sm">Create a password for your invited staff account.</p>
    <form onSubmit={join} className="mt-6 space-y-4"><input required minLength={8} type="password" autoComplete="new-password" placeholder="Password (at least 8 characters)" className="w-full rounded border p-3" value={password} onChange={(e) => setPassword(e.target.value)} /><button disabled={busy || !token} className="rounded bg-sky-700 px-5 py-3 text-white">{busy ? "Joining…" : "Accept invitation"}</button></form>
    {error && <p role="alert" className="mt-3 text-red-700">{error}</p>}{!token && <p className="mt-3 text-red-700">This invitation link is incomplete.</p>}
  </AuthShell>;
}

export default function PlatformJoinPage() {
  return <Suspense fallback={<div>Loading invitation…</div>}><JoinForm /></Suspense>;
}
