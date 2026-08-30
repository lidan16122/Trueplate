import { useCallback, useState } from "react";
import { useSearchParams } from "react-router";

import { GoogleSignInButton } from "@/auth/GoogleSignInButton";
import { useAuth } from "@/auth/useAuth";
import { ErrorNote, Logo } from "@/components/ui";

const HEADLINE = "Know what you ate, not what you guessed.";
const SUBHEAD =
  "Photograph a meal. Trueplate estimates the portions, you correct them, the numbers come from a food database.";

// The server's failure vocabulary for the redirect flow, turned into something a
// person can act on. Sign-in leaves the page entirely now, so a failure returns
// the user to a screen identical to the one they left — silent, which is exactly
// the state three earlier attempts at this bug left the app in.
//
// Mapped, never rendered raw. The query param is whatever is in the address bar;
// React escapes it so it is not XSS, but echoing it would let a crafted link
// print arbitrary text inside our own chrome — a convincing place to leave a
// phone number. Anything unrecognised renders nothing.
const REDIRECT_ERRORS: Record<string, string | undefined> = {
  state: "That sign-in attempt expired or was interrupted. Please try again.",
  google: "Google did not finish the sign-in.",
  exchange: "Could not reach Google to finish signing in. Please try again.",
  verification: "Google sign-in could not be verified.",
  email_in_use: "That email is already registered with a different sign-in method.",
  unavailable: "Google sign-in is unavailable right now.",
};

export function SignIn() {
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

  const googleButton = (
    <GoogleSignInButton
      onCredential={handleCredential}
      disabled={busy}
      className="flex h-14 w-full items-center justify-center gap-3 rounded-lg bg-ink text-lead font-semibold text-white transition-colors hover:bg-accent disabled:opacity-60 md:h-[52px] md:w-auto md:px-[26px]"
    >
      <span className="flex h-[22px] w-[22px] items-center justify-center rounded-full bg-white text-caption font-bold text-ink">
        G
      </span>
      {busy ? "Signing in…" : "Continue with Google"}
    </GoogleSignInButton>
  );

  return (
    <div className="flex min-h-dvh flex-col bg-surface md:flex-row">
      {/* Copy side */}
      <div className="flex flex-1 flex-col justify-between px-7 pt-12 pb-11 md:justify-center md:px-[88px] md:py-0">
        <div className="flex flex-1 flex-col justify-center gap-[18px] md:flex-none md:gap-[22px]">
          <Logo />
          <h1 className="text-[38px] leading-[1.05] font-semibold tracking-[-0.03em] text-balance text-ink md:max-w-[520px] md:text-[52px] md:tracking-[-0.035em]">
            {HEADLINE}
          </h1>
          <p className="text-lead leading-relaxed text-pretty text-muted md:max-w-[460px] md:text-[17px]">
            {SUBHEAD}
          </p>
        </div>

        <div className="relative flex flex-col gap-4 md:flex-row md:items-center md:gap-4 md:pt-2">
          {googleButton}
          <p className="text-center text-label leading-relaxed text-subtle md:max-w-[200px] md:text-left md:text-caption">
            Trueplate is a measurement tool, not medical advice.
          </p>
          {message && (
            <div className="md:absolute md:top-full md:left-0 md:mt-3 md:w-[420px]">
              <ErrorNote>{message}</ErrorNote>
            </div>
          )}
        </div>
      </div>

      {/* Ink panel — desktop only. */}
      <aside className="hidden w-[520px] flex-none flex-col justify-end gap-5 bg-ink p-14 md:flex">
        <div className="flex h-[300px] items-center justify-center rounded-lg border border-dashed border-line-dark font-mono text-label tracking-[0.08em] text-on-dark-dim">
          PHOTO — MEAL ON A TABLE
        </div>
        <p className="text-caption leading-relaxed text-pretty text-on-dark">
          Every estimate is a proposal. You confirm the portion before anything is saved.
        </p>
      </aside>
    </div>
  );
}
