"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

import { PageHeader } from "@/components/layout/PageHeader";
import { AlertBanner } from "@/components/ui/alert-banner";
import { studioConnApi } from "@/lib/studio";

export default function OAuthCallbackPage() {
  return <Suspense fallback={null}><Callback /></Suspense>;
}

/**
 * Where the provider sends the person back after consent. The code is
 * exchanged by the server — with the PKCE verifier only the server holds —
 * and the state is single-use and bound to the person who started it.
 */
function Callback() {
  const params = useSearchParams();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const providerError = params.get("error");
    const state = params.get("state");
    const code = params.get("code");
    if (providerError) {
      setError(`The provider did not authorise the connection: ${params.get("error_description") ?? providerError}.`);
      return;
    }
    if (!state || !code) {
      setError("This page was opened without an authorisation code. Start again from the connection.");
      return;
    }
    studioConnApi.oauthFinish(state, code)
      .then((c) => router.replace(`/studio/connections/${c.id}`))
      .catch((e) => setError(e instanceof Error ? e.message : "The authorisation could not be completed."));
  }, [params, router]);
  return (
    <div className="space-y-4">
      <PageHeader eyebrow="PeopleOps Studio" title="Connecting…" />
      {error ? (
        <AlertBanner variant="error" title="Not connected">{error} <Link href="/studio/connections" className="font-semibold underline">Connections</Link></AlertBanner>
      ) : <p className="text-sm text-ink-500">Completing the authorisation with the provider.</p>}
    </div>
  );
}
