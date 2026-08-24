"use client";

/**
 * Client-side session state.
 *
 * The token lives in `localStorage` and is attached per request by `lib/api.ts`.
 * That is a deliberate trade-off worth being able to defend: a token in
 * `localStorage` is readable by any script that gets injected into the page,
 * whereas an httpOnly cookie is not — but a cookie needs a same-site deployment
 * and CSRF protection, which this split frontend/backend layout does not have.
 * For a single-user research tool the bearer-token model is the honest choice;
 * a clinical deployment should move to httpOnly cookies plus CSRF tokens.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { api, clearSession, getStoredUser, getToken, storeSession } from "@/lib/api";
import type { User } from "@/lib/types";

interface AuthState {
  user: User | null;
  ready: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, fullName?: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const router = useRouter();

  useEffect(() => {
    const stored = getStoredUser();
    if (stored && getToken()) {
      setUser(stored);
      // Confirm with the server: a stored user with an expired token would
      // otherwise render a logged-in shell that 401s on every panel.
      api
        .me()
        .then(setUser)
        .catch(() => {
          clearSession();
          setUser(null);
        })
        .finally(() => setReady(true));
    } else {
      setReady(true);
    }
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const response = await api.login(email, password);
    storeSession(response.access_token, response.user);
    setUser(response.user);
  }, []);

  const signUp = useCallback(async (email: string, password: string, fullName?: string) => {
    const response = await api.register(email, password, fullName);
    storeSession(response.access_token, response.user);
    setUser(response.user);
  }, []);

  const signOut = useCallback(() => {
    clearSession();
    setUser(null);
    router.push("/login");
  }, [router]);

  const value = useMemo(
    () => ({ user, ready, signIn, signUp, signOut }),
    [user, ready, signIn, signUp, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}

/** Wraps a page that requires a session. */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, ready } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (ready && !user) router.replace("/login");
  }, [ready, user, router]);

  if (!ready) {
    return (
      <div className="mx-auto max-w-5xl space-y-4 p-8">
        <div className="skeleton h-8 w-56" />
        <div className="skeleton h-40 w-full" />
      </div>
    );
  }
  if (!user) return null;
  return <>{children}</>;
}
