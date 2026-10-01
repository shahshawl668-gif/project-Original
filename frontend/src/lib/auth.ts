import { apiFetch, clearTokens, parseEnvelopeResponse, setTokens } from "@/lib/api";

export type AuthUser = {
  id: string;
  email: string;
  company_name: string | null;
  role: string;
  platform_role?: string | null;
};

type TokenPair = { access_token: string; refresh_token: string };

/**
 * The password was right and the account has two-step sign-in. Carries the
 * short-lived challenge the second step is answered against; it is held in
 * memory only and opens nothing on its own.
 */
export class SecondStepRequired extends Error {
  constructor(public readonly mfaToken: string) {
    super("Enter the code from your authenticator app.");
    this.name = "SecondStepRequired";
  }
}

type SignInAnswer = Partial<TokenPair> & { mfa_required?: boolean; mfa_token?: string };

async function establish(path: string, body: unknown): Promise<AuthUser> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30_000);
  try {
    const response = await apiFetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
      cache: "no-store",
    });
    const tokens = await parseEnvelopeResponse<SignInAnswer>(response);
    if (tokens?.mfa_required && tokens.mfa_token) {
      throw new SecondStepRequired(tokens.mfa_token);
    }
    if (!tokens?.access_token || !tokens?.refresh_token) {
      throw new Error("The sign-in service returned an incomplete session. Please try again.");
    }
    setTokens(tokens.access_token, tokens.refresh_token);
    // These tokens were just issued; a 401 must fail sign-in rather than start
    // an unbounded refresh request outside this attempt's timeout.
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
    if (error instanceof SecondStepRequired) throw error;
    if (controller.signal.aborted) {
      throw new Error("Sign-in took too long. Please try again.");
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

/** Complete sign-in only after the token and profile requests both succeed. */
export async function signIn(email: string, password: string, workspaceSlug?: string, portal: "client" | "platform" = "client"): Promise<AuthUser> {
  return establish(portal === "platform" ? "/api/auth/platform-login" : "/api/auth/login",
    { email: email.trim(), password, workspace_slug: workspaceSlug });
}

/** The second step: a six-digit code, or one of the recovery codes. */
export async function completeSecondStep(mfaToken: string, code: string): Promise<AuthUser> {
  return establish("/api/auth/mfa/verify", { mfa_token: mfaToken, code: code.trim() });
}
