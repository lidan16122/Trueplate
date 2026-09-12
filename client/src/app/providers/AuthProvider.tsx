import { useCallback, useEffect, useMemo, useState } from "react";

import { authApi } from "@/services/auth";
import { onSessionExpired } from "@/services/http";
import type { User } from "@/types/auth";

import { AuthContext, type AuthState } from "@/models/auth";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [needsOnboarding, setNeedsOnboarding] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  // Session discovery treats a signed-out visitor as a normal result.
  // The server checks the httpOnly cookies and preserves refresh recovery when possible.
  useEffect(() => {
    let cancelled = false;

    authApi
      .session()
      .then((session) => {
        if (cancelled) return;
        setUser(session?.user ?? null);
        setNeedsOnboarding(session?.needs_onboarding ?? false);
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
    const session = await authApi.signInWithGoogle(credential);
    setNeedsOnboarding(session.needs_onboarding);
    setUser(session.user);
  }, []);

  const signOut = useCallback(async () => {
    try {
      await authApi.logout();
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
      const session = await authApi.me();
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
