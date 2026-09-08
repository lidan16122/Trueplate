import { useAuth } from "@/hooks/useAuth";
import { useCallback, useState } from "react";
import { useSearchParams } from "react-router";
import { REDIRECT_ERRORS } from "../models/redirectErrors";


/** Coordinates sign-in errors with the session provider, which owns the post-login destination. */
export function useSignIn() {
  const { signIn } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [params] = useSearchParams();

  // Left in the URL rather than stripped on mount: it is the one thing a user
  // can copy into a bug report, and a sign-in screen has nothing to lose by it.
  const message = error ?? REDIRECT_ERRORS[params.get("error") ?? ""] ?? null;

  const handleCredential = useCallback(
    async (credential: string) => {
      setBusy(true);
      setError(null);
      try {
        // No navigation here on purpose. Setting the user re-renders
        // PublicOnlyRoute, which owns the destination and sends a user with no
        // profile to the wizard. Navigating here as well raced that guard, and
        // the guard won — which is how the design's signin -> wizard edge got
        // silently skipped.
        await signIn(credential);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Sign-in failed");
      } finally {
        setBusy(false);
      }
    },
    [signIn],
  );


  return { busy, message, handleCredential };
}
