"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";

import {
  apiFetch,
  clearTokens,
  getAccessToken,
  getRefreshToken,
  parseEnvelopeResponse,
  parseJwtPayload,
  refreshSession,
  setTokens,
} from "@/lib/api";

import { signIn, type AuthUser } from "@/lib/auth";
export type { AuthUser } from "@/lib/auth";

type AuthContextValue = {
  user: AuthUser | null;
  loading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string, company_name?: string | null) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

type TokenPair = { access_token: string; refresh_token: string };

async function loadUser(): Promise<AuthUser> {
  const res = await apiFetch("/api/auth/me", { cache: "no-store" });
  return parseEnvelopeResponse<AuthUser>(res);
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const sessionRevision = useRef(0);

  const refreshUser = useCallback(async () => {
    if (typeof window === "undefined") return;
    const revision = sessionRevision.current;
    let access = getAccessToken();
    if (!access && getRefreshToken()) {
      await refreshSession();
      access = getAccessToken();
    }
    if (!access) {
      if (revision === sessionRevision.current) setUser(null);
      return;
    }
    try {
      const me = await loadUser();
      if (revision === sessionRevision.current) setUser(me);
    } catch {
      // An old session check must not clear a newly signed-in session.
      if (revision === sessionRevision.current) {
        clearTokens();
        setUser(null);
      }
    }
  }, []);

  useEffect(() => {
    void refreshUser().finally(() => setLoading(false));
  }, [refreshUser]);

  /** Rotate access tokens before expiry (access JWT `exp`). */
  useEffect(() => {
    const proactive = async () => {
      const access = getAccessToken();
      const rt = getRefreshToken();
      if (!access || !rt) return;
      const payload = parseJwtPayload(access);
      if (!payload?.exp) return;
      const now = Math.floor(Date.now() / 1000);
      if (payload.exp - now < 150) {
        await refreshSession();
      }
    };

    void proactive();
    const id = window.setInterval(() => void proactive(), 45_000);
    return () => window.clearInterval(id);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    sessionRevision.current += 1;
    const me = await signIn(email, password);
    setUser(me);
    setLoading(false);
    toast.success("Signed in");
  }, []);

  const signup = useCallback(
    async (email: string, password: string, company_name?: string | null) => {
      sessionRevision.current += 1;
      const res = await apiFetch("/api/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, company_name }),
      });
      const body = await res.json();
      if (!res.ok || !body.success) {
        const msg =
          typeof body?.error?.detail === "string"
            ? body.error.detail
            : "Signup failed";
        toast.error(msg);
        throw new Error(msg);
      }
      const tokens = body.data as TokenPair;
      setTokens(tokens.access_token, tokens.refresh_token);
      const me = await loadUser();
      setUser(me);
      toast.success("Account created");
    },
    []
  );

  const logout = useCallback(async () => {
    sessionRevision.current += 1;
    const refresh = getRefreshToken();
    clearTokens();
    setUser(null);
    if (refresh) {
      try {
        await apiFetch("/api/auth/logout", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refresh }),
        });
      } catch {
        /* ignore */
      }
    }
    toast.success("Signed out");
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      isAuthenticated: !!user,
      login,
      signup,
      logout,
      refreshUser,
    }),
    [user, loading, login, signup, logout, refreshUser]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
