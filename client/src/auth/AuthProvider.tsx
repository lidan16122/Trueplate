import { useCallback, useEffect, useMemo, useState } from "react";

import { api, onSessionExpired } from "@/lib/api";
import type { User } from "@/types/api";

import { AuthContext, type AuthState } from "./AuthContext";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // On boot the only way to know whether a session exists is to ask: the auth
  // cookies are httpOnly, so their presence is invisible to JavaScript.
  useEffect(() => {
    let cancelled = false;

    api.auth
      .me()
      .then((me) => {
        if (!cancelled) setUser(me);
      })
      .catch(() => {
        if (!cancelled) setUser(null);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // A refresh can fail mid-session, in a request this provider never made.
  // Without this the UI would keep rendering a signed-in shell over 401s.
  useEffect(() => onSessionExpired(() => setUser(null)), []);

  const signIn = useCallback(async (credential: string) => {
    const response = await api.auth.signInWithGoogle(credential);
    setUser(response.user);
    return { needsOnboarding: response.needs_onboarding };
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.auth.logout();
    } finally {
      // Clear locally even if the request failed — the user asked to be signed
      // out, and leaving them looking signed in would be worse than a stale
      // server-side session that expires on its own.
      setUser(null);
    }
  }, []);

  const refreshUser = useCallback(async () => {
    try {
      setUser(await api.auth.me());
    } catch {
      setUser(null);
    }
  }, []);

  const value = useMemo<AuthState>(
    () => ({ user, isLoading, signIn, signOut, refreshUser }),
    [user, isLoading, signIn, signOut, refreshUser],
  );

  return <AuthContext value={value}>{children}</AuthContext>;
}
