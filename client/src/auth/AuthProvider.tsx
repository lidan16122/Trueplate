import { useCallback, useEffect, useMemo, useState } from "react";

import { api, onSessionExpired } from "@/lib/api";
import type { User } from "@/types/api";

import { AuthContext, type AuthState } from "./AuthContext";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [needsOnboarding, setNeedsOnboarding] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  // On boot the only way to know whether a session exists is to ask: the auth
  // cookies are httpOnly, so their presence is invisible to JavaScript. The same
  // call reports whether the wizard is outstanding, which is equally invisible.
  useEffect(() => {
    let cancelled = false;

    api.auth
      .me()
      .then((session) => {
        if (cancelled) return;
        setUser(session.user);
        setNeedsOnboarding(session.needs_onboarding);
      })
      .catch(() => {
        if (cancelled) return;
        setUser(null);
        setNeedsOnboarding(false);
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

  // Returns nothing: the destination is the guards' call, not the caller's.
  // Handing back `needsOnboarding` is what let SignIn navigate on its own and
  // race PublicOnlyRoute, which had already sent the user to /today.
  const signIn = useCallback(async (credential: string) => {
    const session = await api.auth.signInWithGoogle(credential);
    setNeedsOnboarding(session.needs_onboarding);
    setUser(session.user);
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.auth.logout();
    } finally {
      // Clear locally even if the request failed — the user asked to be signed
      // out, and leaving them looking signed in would be worse than a stale
      // server-side session that expires on its own. Both fields go together:
      // they describe one session, and a stale `needsOnboarding` outliving the
      // user it belonged to is how the next sign-in inherits the wrong route.
      setUser(null);
      setNeedsOnboarding(false);
    }
  }, []);

  const completeOnboarding = useCallback(() => setNeedsOnboarding(false), []);

  // Re-reads the whole session, `needs_onboarding` included. Note the catch
  // treats any failure as a lost session, so this belongs on paths that can
  // afford to end at the sign-in screen — not on the wizard's save path, where
  // a transient blip would discard work the server has already accepted.
  const refreshUser = useCallback(async () => {
    try {
      const session = await api.auth.me();
      setUser(session.user);
      setNeedsOnboarding(session.needs_onboarding);
    } catch {
      setUser(null);
      setNeedsOnboarding(false);
    }
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      isLoading,
      needsOnboarding,
      signIn,
      signOut,
      completeOnboarding,
      refreshUser,
    }),
    [user, isLoading, needsOnboarding, signIn, signOut, completeOnboarding, refreshUser],
  );

  return <AuthContext value={value}>{children}</AuthContext>;
}
