"use client";

/**
 * Authentication is disabled.
 * AuthProvider and useAuth are kept as stubs so existing component
 * imports continue to compile without changes.
 */
import { createContext, useContext } from "react";

type User = {
  id: string;
  email: string;
  company_name: string | null;
};

type AuthContextValue = {
  user: User;
  loading: false;
  login: () => Promise<void>;
  signup: () => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
};

const SYSTEM_USER: User = {
  id: "system",
  email: "system@payrollcheck.local",
  company_name: "PayrollCheck",
};

const noop = async () => {};

const AuthContext = createContext<AuthContextValue>({
  user: SYSTEM_USER,
  loading: false,
  login: noop,
  signup: noop,
  logout: noop,
  refreshUser: noop,
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  return (
    <AuthContext.Provider
      value={{ user: SYSTEM_USER, loading: false, login: noop, signup: noop, logout: noop, refreshUser: noop }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
