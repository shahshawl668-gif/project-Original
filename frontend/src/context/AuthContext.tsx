"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { toast } from "sonner";

import {
  ACCESS_TOKEN_KEY,
  apiAbsoluteUrl,
  apiFetch,
  clearTokens,
  getAccessToken,
  getRefreshToken,
  parseEnvelopeResponse,
  parseJwtPayload,
  refreshSession,
  setTokens,
} from "@/lib/api";

export type AuthUser = {
  id: string;
  email: string;
  company_name: string | null;
  role: string;
};

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
  const res = await apiFetch("/api/auth/me");
  return parseEnvelopeResponse<AuthUser>(res);
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshUser = useCallback(async () => {
    if (typeof window === "undefined") return;
    let access = getAccessToken();
    if (!access && getRefreshToken()) {
      await refreshSession();
      access = getAccessToken();
    }
    if (!access) {
      setUser(null);
      return;
    }
    try {
      const me = await loadUser();
      setUser(me);
    } catch {
      clearTokens();
      setUser(null);
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
    const res = await fetch(apiAbsoluteUrl("/api/auth/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const body = await res.json();
    if (!res.ok || !body.success) {
      const msg =
        typeof body?.error?.detail === "string"
          ? body.error.detail
          : "Login failed";
      toast.error(msg);
      throw new Error(msg);
    }
    const tokens = body.data as TokenPair;
    setTokens(tokens.access_token, tokens.refresh_token);
    const me = await loadUser();
    setUser(me);
    toast.success("Signed in");
  }, []);

  const signup = useCallback(
    async (email: string, password: string, company_name?: string | null) => {
      const res = await fetch(apiAbsoluteUrl("/api/auth/signup"), {
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
    const refresh = getRefreshToken();
    clearTokens();
    setUser(null);
    if (refresh) {
      try {
        await fetch(apiAbsoluteUrl("/api/auth/logout"), {
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
