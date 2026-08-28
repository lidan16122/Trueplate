import { useEffect, useLayoutEffect, useRef, useState } from "react";

const GSI_SRC = "https://accounts.google.com/gsi/client";

/** Google's own cap on `renderButton`'s width. Anything wider is stretched. */
const GSI_MAX_WIDTH = 400;

/** Used only when the container cannot be measured, so the button still works. */
const GSI_FALLBACK_WIDTH = 320;

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
 * layout. So the real button is laid *invisibly over* ours: the user sees our
 * design and clicks Google's actual control.
 *
 * The obvious alternative — render Google's button off-screen and forward a
 * click to it — is what this used to do, and it broke sign-in in production
 * with no visible symptom. `HTMLElement.click()` dispatches an event carrying
 * `isTrusted: false`, and browsers gate `window.open` on genuine user
 * activation, so the popup was blocked and GSI reported it to the console and
 * nowhere else. An overlay keeps the gesture real, which is the only thing that
 * reliably satisfies a popup blocker.
 */
export function GoogleSignInButton({ onCredential, disabled, children, className }: Props) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Google renders at a fixed pixel width, so the overlay has to be told how
  // wide our button actually is — which only the layout knows, and which
  // changes at the md breakpoint.
  const [width, setWidth] = useState(0);
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;

  useLayoutEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;
    // Measured directly *and* observed. The observer alone is not enough: there
    // are environments where it never fires, and a width stuck at zero would be
    // the difference between a working sign-in button and a dead one — which is
    // exactly the class of silent failure this component is being fixed for.
    const measure = () => setWidth(wrapper.getBoundingClientRect().width);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(wrapper);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!clientId) {
      setError("Google sign-in is not configured");
      return;
    }

    let cancelled = false;

    loadGsi()
      .then(() => {
        const overlay = overlayRef.current;
        if (cancelled || !window.google || !overlay) return;

        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: (response) => void onCredential(response.credential),
          cancel_on_tap_outside: false,
        });
        // Re-rendered whenever the width changes; GSI appends rather than
        // replaces, so the previous button has to go or they stack.
        overlay.replaceChildren();
        window.google.accounts.id.renderButton(overlay, {
          type: "standard",
          size: "large",
          // Falls back rather than skipping. An unmeasured width renders a
          // button that is merely the wrong size — still invisible, still
          // clickable — where skipping renders nothing to click at all.
          width: Math.min(Math.round(width) || GSI_FALLBACK_WIDTH, GSI_MAX_WIDTH),
        });
        setReady(true);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      });

    return () => {
      cancelled = true;
    };
  }, [clientId, onCredential, width]);

  return (
    <>
      <div ref={wrapperRef} className="group relative w-full md:w-auto">
        {/* Presentational. The real control is the Google button above it, so
            this is hidden from assistive tech and taken out of the tab order —
            two buttons announcing the same action is worse than one. */}
        <button
          type="button"
          aria-hidden
          tabIndex={-1}
          disabled={disabled || !ready}
          className={`${className ?? ""} group-focus-within:ring-2 group-focus-within:ring-accent`}
        >
          {children}
        </button>

        {/* Google's button, invisible but genuinely clicked. `scaleX` covers a
            container wider than Google's 400px ceiling — the distortion cannot
            be seen at zero opacity, and a dead strip at the edge of a button
            that looks whole would be far worse. */}
        <div
          ref={overlayRef}
          className={`absolute inset-0 origin-left overflow-hidden opacity-0 ${
            disabled || !ready ? "pointer-events-none" : ""
          }`}
          style={
            width > GSI_MAX_WIDTH ? { transform: `scaleX(${width / GSI_MAX_WIDTH})` } : undefined
          }
        />
      </div>

      {error && <p className="text-center text-label text-warn">{error}</p>}
    </>
  );
}
