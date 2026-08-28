import { useEffect, useRef, useState } from "react";

const GSI_SRC = "https://accounts.google.com/gsi/client";

interface CredentialResponse {
  credential: string;
}

interface GoogleAccounts {
  accounts: {
    id: {
      initialize: (config: {
        client_id: string;
        callback: (response: CredentialResponse) => void;
        cancel_on_tap_outside?: boolean;
      }) => void;
      prompt: () => void;
      renderButton: (parent: HTMLElement, options: Record<string, unknown>) => void;
    };
  };
}

declare global {
  interface Window {
    google?: GoogleAccounts;
  }
}

let scriptPromise: Promise<void> | null = null;

/** Load Google Identity Services once, however many buttons ask for it. */
function loadGsi(): Promise<void> {
  scriptPromise ??= new Promise((resolve, reject) => {
    if (window.google?.accounts?.id) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = GSI_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Could not load Google Sign-In"));
    document.head.appendChild(script);
  });
  return scriptPromise;
}

interface Props {
  onCredential: (credential: string) => void | Promise<void>;
  disabled?: boolean;
}

/**
 * Google's own sign-in button, rendered the way Google documents it.
 *
 * The design would rather this wore the app's button, and an earlier version
 * tried: Google's button was rendered off-screen and a click forwarded to it
 * from a styled one. That broke sign-in in production with no visible symptom.
 * `HTMLElement.click()` produces an event carrying `isTrusted: false`, browsers
 * gate `window.open` on genuine user activation, and the popup was refused —
 * reported to the console and nowhere else.
 *
 * The deeper problem is that there is no supported way to do it. Google's API
 * offers `renderButton` and nothing else: `prompt()` drives One Tap only, and
 * `click_listener` observes a click without being able to start the flow. Any
 * custom button is therefore a workaround resting on Google's DOM shape and on
 * browser activation rules, neither of which is a contract.
 *
 * So this takes the supported path and accepts Google's styling. `filled_black`
 * and `continue_with` are the closest of the documented options to the design's
 * dark button — not the same, and that is the trade being made.
 */
export function GoogleSignInButton({ onCredential, disabled }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;

  useEffect(() => {
    if (!clientId) {
      setError("Google sign-in is not configured");
      return;
    }

    let cancelled = false;

    loadGsi()
      .then(() => {
        const host = hostRef.current;
        if (cancelled || !window.google || !host) return;

        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: (response) => void onCredential(response.credential),
          cancel_on_tap_outside: false,
        });
        // `filled_black` and `continue_with` get the markup closest to the
        // design before CSS touches it, so the button never flashes as a white
        // Google button on the way to being a dark one. No `width`: Google caps
        // it at 400px, and `.gsi-themed` overrides the width anyway.
        window.google.accounts.id.renderButton(host, {
          type: "standard",
          theme: "filled_black",
          text: "continue_with",
          shape: "rectangular",
          size: "large",
        });
        setReady(true);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });

    return () => {
      cancelled = true;
    };
  }, [clientId, onCredential]);

  return (
    <>
      {/* `gsi-themed` is where the design is applied — see index.css. Google's
          button has no disabled state, so an in-flight sign-in is shown by
          dimming it and taking it out of reach. */}
      <div
        ref={hostRef}
        className={`gsi-themed w-full${
          disabled || !ready ? " pointer-events-none opacity-60" : ""
        }`}
      />

      {error && <p className="text-center text-label text-warn">{error}</p>}
    </>
  );
}
