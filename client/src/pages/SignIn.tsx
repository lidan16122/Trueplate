import { useCallback, useState } from "react";

import { GoogleSignInButton } from "@/auth/GoogleSignInButton";
import { useAuth } from "@/auth/useAuth";
import { ErrorNote, Logo } from "@/components/ui";

const HEADLINE = "Know what you ate, not what you guessed.";
const SUBHEAD =
  "Photograph a meal. Trueplate estimates the portions, you correct them, the numbers come from a food database.";

export function SignIn() {
  const { signIn } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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

  // Values from the design canvas: 56px tall and full width on mobile at a 16px
  // radius, 52px and content-width on desktop at 14px. The radius genuinely
  // differs between the two, which is why it is not a single token.
  const googleButton = (
    <GoogleSignInButton
      onCredential={handleCredential}
      disabled={busy}
      className="flex h-14 w-full items-center justify-center gap-3 rounded-lg bg-ink text-lead font-semibold text-white transition-colors hover:bg-accent disabled:opacity-60 md:h-[52px] md:w-auto md:rounded-[14px] md:px-[26px]"
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
          {error && (
            <div className="md:absolute md:top-full md:left-0 md:mt-3 md:w-[420px]">
              <ErrorNote>{error}</ErrorNote>
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
