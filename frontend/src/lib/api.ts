/** When true, the browser calls same-origin `/api/proxy/api/…` and the Next.js server forwards to BACKEND_URL (avoids CORS / browser TLS issues). */
function usesServerSideProxy(): boolean {
  const forceDirect =
    process.env.NEXT_PUBLIC_DIRECT_API === "1" ||
    process.env.NEXT_PUBLIC_DIRECT_API === "true";
  if (forceDirect) return false;

  const relay = process.env.NEXT_PUBLIC_USE_API_RELAY;
  if (relay === "0" || relay === "false") return false;
  if (relay === "1" || relay === "true") return true;

  if (typeof window !== "undefined") {
    const h = window.location.hostname;
    if (h === "peopleopslab.in" || h === "www.peopleopslab.in") return true;
  }
  return false;
}

/**
 * Public URL for an API route (must start with `/api/…`).
 * - On peopleopslab.in (automatic) or NEXT_PUBLIC_USE_API_RELAY=1 → `/api/proxy/api/…` (needs BACKEND_URL on server).
 * - Else → `{origin}{path}` using NEXT_PUBLIC_API_URL or inferred `https://api.peopleopslab.in` when not proxied.
 */
export function apiAbsoluteUrl(apiPath: string): string {
  const path = apiPath.startsWith("/") ? apiPath : `/${apiPath}`;
  if (usesServerSideProxy()) {
    return `/api/proxy${path}`;
  }
  const base = resolvedApiOrigin();
  return `${base}${path}`;
}

function resolvedApiOrigin(): string {
  const env = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (env) return env.replace(/\/$/, "");

  if (typeof window !== "undefined") {
    const h = window.location.hostname;
    if (h === "peopleopslab.in" || h === "www.peopleopslab.in") {
      return "https://api.peopleopslab.in";
    }
  }
  return "http://localhost:8000";
}

function directApiUrl(path: string): string {
  return `${resolvedApiOrigin()}${path}`;
}

/** Human-readable hint for dashboards. */
export function getApiTargetDescription(): string {
  if (usesServerSideProxy()) {
    return "/api/proxy (Next.js → BACKEND_URL) — set BACKEND_URL on the server (e.g. Vercel)";
  }
  const env = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (env) return env.replace(/\/$/, "");
  if (typeof window !== "undefined") {
    const h = window.location.hostname;
    if (h === "peopleopslab.in" || h === "www.peopleopslab.in") {
      return "https://api.peopleopslab.in (direct — prefer BACKEND_URL + /api/proxy; see README)";
    }
  }
  return "http://localhost:8000";
}

export const ACCESS_TOKEN_KEY = "payroll_saas_access_token";
export const REFRESH_TOKEN_KEY = "payroll_saas_refresh_token";

export type ApiEnvelope<T> = {
  success: boolean;
  data: T;
  error: { detail?: unknown; code?: string } | null;
};

export type TokenPairData = {
  access_token: string;
  refresh_token: string;
  token_type?: string;
};

/** Decode JWT payload (browser only; no crypto verification — used for expiry scheduling). */
export function parseJwtPayload(token: string): { exp?: number } | null {
  try {
    const parts = token.split(".");
    if (parts.length < 2) return null;
    const b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const pad = b64.length % 4 === 0 ? "" : "=".repeat(4 - (b64.length % 4));
    const json = atob(b64 + pad);
    return JSON.parse(json) as { exp?: number };
  } catch {
    return null;
  }
}

function authHeader(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const t = localStorage.getItem(ACCESS_TOKEN_KEY);
  return t ? { Authorization: `Bearer ${t}` } : {};
}

/** Logical `/api/...` path passed to apiFetch — used for refresh suppression rules. */
function shouldNeverRefresh401(logicalPath: string): boolean {
  const p = logicalPath.split("?")[0];
  return (
    p.endsWith("/api/auth/refresh") ||
    p.endsWith("/api/auth/login") ||
    p.endsWith("/api/auth/signup") ||
    p.endsWith("/api/auth/password-reset-request") ||
    p.endsWith("/api/auth/password-reset-confirm")
  );
}

let refreshMutex: Promise<boolean> | null = null;

async function shouldFallbackToDirect(res: Response): Promise<boolean> {
  if (res.status !== 502) return false;
  try {
    const body = (await res.clone().json()) as ApiEnvelope<unknown>;
    const code = body?.error?.code;
    return code === "proxy_misconfigured" || code === "upstream_unreachable";
  } catch {
    return false;
  }
}

async function fetchWithProxyFallback(path: string, init: RequestInit): Promise<Response> {
  const usingProxy = usesServerSideProxy();
  try {
    const res = await fetch(apiAbsoluteUrl(path), init);
    if (usingProxy && (await shouldFallbackToDirect(res))) {
      try {
        const direct = await fetch(directApiUrl(path), init);
        if (direct.status !== 502) return direct;
      } catch {
        // Keep original proxy response if direct fallback also fails.
      }
    }
    return res;
  } catch (e) {
    if (usingProxy && e instanceof TypeError) {
      // Proxy path itself is unreachable; attempt direct API call.
      return fetch(directApiUrl(path), init);
    }
    throw e;
  }
}

/**
 * Ask the backend for a new access+refresh pair. Returns false if refresh_token is invalid.
 * Updates localStorage when successful.
 */
export async function refreshSession(): Promise<boolean> {
  if (typeof window === "undefined") return false;
  const rt = localStorage.getItem(REFRESH_TOKEN_KEY);
  if (!rt) return false;

  if (!refreshMutex) {
    refreshMutex = (async () => {
      try {
        const res = await fetchWithProxyFallback("/api/auth/refresh", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: rt }),
        });
        const text = await res.text();
        let body: ApiEnvelope<TokenPairData> | null = null;
        try {
          body = text ? (JSON.parse(text) as ApiEnvelope<TokenPairData>) : null;
        } catch {
          return false;
        }
        if (!res.ok || !body?.success || !body.data?.access_token || !body.data?.refresh_token) {
          clearTokens();
          return false;
        }
        setTokens(body.data.access_token, body.data.refresh_token);
        return true;
      } catch {
        return false;
      } finally {
        refreshMutex = null;
      }
    })();
  }
  return refreshMutex;
}

/**
 * Authenticated fetch. On **401**, attempts one silent refresh when a refresh token exists,
 * then retries the request once.
 */
export async function apiFetch(path: string, init: RequestInit = {}, isRetry = false): Promise<Response> {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const a = authHeader();
  if (!headers.has("Authorization") && a.Authorization) {
    headers.set("Authorization", a.Authorization);
  }

  const requestInit: RequestInit = { ...init, headers };
  let res: Response;
  try {
    res = await fetchWithProxyFallback(path, requestInit);
  } catch (e) {
    if (typeof window !== "undefined" && e instanceof TypeError) {
      const hint = getApiTargetDescription();
      throw new Error(
        `Failed to fetch (${e.message}). Target: ${hint}. If using peopleopslab.in, set BACKEND_URL on Vercel. Otherwise set NEXT_PUBLIC_API_URL.`,
      );
    }
    throw e;
  }

  if (
    res.status === 401 &&
    !isRetry &&
    typeof window !== "undefined" &&
    !shouldNeverRefresh401(path) &&
    localStorage.getItem(REFRESH_TOKEN_KEY)
  ) {
    const rotated = await refreshSession();
    if (rotated) {
      return apiFetch(path, init, true);
    }
  }

  return res;
}

function formatErrorDetail(detail: unknown): string {
  if (detail == null) return "Request failed";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((e) =>
        typeof e === "object" && e && "msg" in e ? String((e as { msg: string }).msg) : JSON.stringify(e)
      )
      .join("; ");
  }
  if (typeof detail === "object" && detail && "msg" in detail) {
    return String((detail as { msg: string }).msg);
  }
  return JSON.stringify(detail);
}

/** Parse a JSON response using the standard `{ success, data, error }` shape. */
export async function parseEnvelopeResponse<T>(res: Response): Promise<T> {
  const text = await res.text();
  let body: ApiEnvelope<T> | { detail?: unknown } | null = null;
  try {
    body = text ? (JSON.parse(text) as ApiEnvelope<T>) : null;
  } catch {
    throw new Error(`Invalid JSON (${res.status})`);
  }
  const env = body as ApiEnvelope<T>;
  if (!res.ok || !env || env.success !== true) {
    const errObj = env && typeof env === "object" && "error" in env ? env.error : null;
    const fallback =
      typeof body === "object" && body && "detail" in body ? (body as { detail: unknown }).detail : undefined;
    const detail = errObj?.detail ?? fallback ?? `HTTP ${res.status}`;
    throw new Error(formatErrorDetail(detail));
  }
  return env.data;
}

/** Parse standard `{ success, data, error }` JSON responses. */
export async function apiJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await apiFetch(path, init);
  return parseEnvelopeResponse<T>(res);
}

/** For downloads (e.g. Excel) — no JSON envelope. */
export async function apiBlob(path: string, init: RequestInit = {}): Promise<Blob> {
  const res = await apiFetch(path, init);
  if (!res.ok) {
    const text = await res.text();
    let msg = `Download failed (${res.status})`;
    try {
      const j = JSON.parse(text) as ApiEnvelope<unknown>;
      if (j?.error?.detail != null) msg = formatErrorDetail(j.error.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new Error(msg);
  }
  return res.blob();
}

export function setTokens(access: string, refresh: string) {
  localStorage.setItem(ACCESS_TOKEN_KEY, access);
  localStorage.setItem(REFRESH_TOKEN_KEY, refresh);
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

/** Probe API health from the browser; resolves with which routing path actually responded. */
export async function probeApiHealth(): Promise<{
  ok: boolean;
  via: "proxy" | "direct" | "none";
  detail?: string;
  data?: unknown;
}> {
  const path = "/api/health";
  // Try proxy first (if active), then direct.
  const tries: Array<{ via: "proxy" | "direct"; url: string }> = [];
  if (usesServerSideProxy()) {
    tries.push({ via: "proxy", url: `/api/proxy${path}` });
  }
  tries.push({ via: "direct", url: `${resolvedApiOrigin()}${path}` });

  for (const t of tries) {
    try {
      const res = await fetch(t.url, { cache: "no-store" });
      if (res.ok) {
        let data: unknown = undefined;
        try {
          data = await res.json();
        } catch {
          /* tolerate non-JSON */
        }
        return { ok: true, via: t.via, data };
      }
    } catch {
      /* try next */
    }
  }
  return { ok: false, via: "none", detail: "Both proxy and direct API attempts failed" };
}
