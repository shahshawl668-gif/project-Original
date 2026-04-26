export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** Simple fetch wrapper — no auth tokens required. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(`${API_BASE}${path}`, { ...init, headers });
}
