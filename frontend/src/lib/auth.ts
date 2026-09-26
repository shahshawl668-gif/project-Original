import { apiFetch, clearTokens, parseEnvelopeResponse, setTokens } from "@/lib/api";

export type AuthUser = {
  id: string;
  email: string;
  company_name: string | null;
  role: string;
};

type TokenPair = { access_token: string; refresh_token: string };

/** Complete sign-in only after the token and profile requests both succeed. */
export async function signIn(email: string, password: string): Promise<AuthUser> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30_000);
  try {
    const response = await apiFetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email.trim(), password }),
      signal: controller.signal,
      cache: "no-store",
    });
    const tokens = await parseEnvelopeResponse<TokenPair>(response);
    if (!tokens?.access_token || !tokens?.refresh_token) {
      throw new Error("The sign-in service returned an incomplete session. Please try again.");
    }
    setTokens(tokens.access_token, tokens.refresh_token);
    // These tokens were just issued; a 401 must fail sign-in rather than start
    // an unbounded refresh request outside this attempt\'s timeout.
    const profile = await apiFetch("/api/auth/me", {
      signal: controller.signal,
      cache: "no-store",
    }, true);
    const user = await parseEnvelopeResponse<AuthUser>(profile);
    if (!user?.id) throw new Error("Unable to load your profile. Please try signing in again.");
    return user;
  } catch (error) {
    // Do not leave a half-established session after a failed profile request.
    clearTokens();
    if (controller.signal.aborted) {
      throw new Error("Sign-in took too long. Please try again.");
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}
