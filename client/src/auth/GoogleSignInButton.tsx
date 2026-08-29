import { useCallback, useEffect, useRef, useState } from "react";

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
        use_fedcm_for_button?: boolean;
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
  children: React.ReactNode;
  className?: string;
}

/**
 * A Google sign-in trigger wearing the design's own button.
 *
 * Google's `renderButton` draws a button this app cannot use as-is: its logo,
 * its wording and its own localisation, where the design asks for a white "G"
 * disc and "Continue with Google". So the real button is rendered off-screen
 * and clicked programmatically — the visible control is ours and the credential
 * flow is still Google's.
 *
 * This used to say the button "produces an iframe that cannot be restyled".
 * That was true of the old gapi library and is not true of Google Identity
 * Services, which renders into the light DOM — setting `border-radius` on the
 * rendered button takes. Styling it is therefore possible; it is the mark and
 * the copy, which Google's branding terms govern, that rule the approach out.
 */
export function GoogleSignInButton({ onCredential, disabled, children, className }: Props) {
  const hiddenRef = useRef<HTMLDivElement>(null);
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
        if (cancelled || !window.google || !hiddenRef.current) return;

        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: (response) => void onCredential(response.credential),
          cancel_on_tap_outside: false,
          // Sign-in works locally and dies on the deployed origin from the same
          // bundle: Chrome blocks the popup there, and setting the site's popup
          // permission to Allow fixes it. Whatever the reason, it is one script
          // cannot reach — there is no popup permission in the Permissions API
          // and no way to ask the browser to prompt for one.
          //
          // FedCM is the way out because it stops needing a popup at all: Chrome
          // renders sign-in as browser-native UI it owns, so a blocker governing
          // page-opened windows has nothing to act on. Desktop M125+, Android
          // M128+ (google.accounts.id JS reference).
          //
          // Two things this does *not* establish, both worth knowing before
          // trusting it. Google documents no fallback for browsers without
          // FedCM — Safari is expected to keep the popup flow that already works
          // there, but that is inference, not a documented guarantee. And on
          // Chrome older than M125 the popup flow stays, which is precisely what
          // is broken here, so this fixes nothing for those users.
          use_fedcm_for_button: true,
        });
        window.google.accounts.id.renderButton(hiddenRef.current, {
          type: "standard",
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

  const handleClick = useCallback(() => {
    // Click the real (hidden) Google button so the credential flow is
    // untouched — no popup blocked, no reimplemented OAuth.
    const realButton = hiddenRef.current?.querySelector<HTMLElement>('div[role="button"]');
    realButton?.click();
  }, []);

  return (
    <>
      <button
        type="button"
        onClick={handleClick}
        disabled={disabled || !ready}
        className={className}
      >
        {children}
      </button>

      {/* Moved off-viewport rather than collapsed. `display:none` stops GSI
          rendering the button at all, which leaves nothing to click — but the
          h-0/w-0/opacity-0 this used to carry is the shape an anti-clickjacking
          check would object to most, and FedCM is a privacy feature whose
          visibility requirements Google does not document. Off-screen at its
          natural size is the version least likely to be refused, and it looks
          identical: nothing here is ever seen either way. */}
      <div
        ref={hiddenRef}
        aria-hidden
        className="pointer-events-none absolute top-0 -left-[9999px]"
      />

      {error && <p className="text-center text-label text-warn">{error}</p>}
    </>
  );
}
