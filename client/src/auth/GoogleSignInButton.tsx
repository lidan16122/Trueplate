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
 * Google's `renderButton` produces an iframe that cannot be restyled, which
 * would put a stock Google button in the middle of a carefully specified
 * layout. Instead the real button is rendered off-screen and clicked
 * programmatically, so the visible control is ours and the credential flow is
 * still Google's.
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

      {/* Kept in the layout but visually hidden: display:none stops GSI
          rendering the button at all, which leaves nothing to click. */}
      <div
        ref={hiddenRef}
        aria-hidden
        className="pointer-events-none absolute h-0 w-0 overflow-hidden opacity-0"
      />

      {error && <p className="text-center text-label text-warn">{error}</p>}
    </>
  );
}
