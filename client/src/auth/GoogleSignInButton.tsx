// The server owns every Google parameter now — client id, secret, redirect URI,
// and the state cookie — so this component needs no Google configuration at all,
// and VITE_GOOGLE_CLIENT_ID has left the client entirely.
//
// Relative, and deliberately not built from VITE_API_BASE_URL the way lib/api.ts
// builds every other call. The whole flow depends on the browser staying on the
// origin that served the page, because that is the only origin the SameSite=Lax
// auth cookies apply to; an absolute URL here would sign the user in on a host
// they are not on. Paired with the route in server/app/api/routes/auth.py —
// nothing mechanical connects the two.
const SIGN_IN_START = "/api/v1/auth/google/start";

interface Props {
  /**
   * No longer called: nothing in this flow hands a credential to JavaScript.
   * Kept in the props, with POST /auth/google and AuthProvider.signIn behind it,
   * so the popup path is a single revert away.
   */
  onCredential: (credential: string) => void | Promise<void>;
  disabled?: boolean;
  children: React.ReactNode;
  className?: string;
}

/**
 * A Google sign-in trigger wearing the design's own button.
 *
 * It starts sign-in by leaving the page. Every earlier version of this component
 * rendered Google's real button off-screen and forwarded a synthetic `.click()`
 * to it, which asked the browser to open a popup — and on the deployed origin
 * Chrome refused, with no prompt and no permission a script can request. A
 * top-level navigation is not gated that way, so this cannot fail for that
 * reason.
 *
 * A <button> and not an <a>, even though this is a navigation: an anchor offers
 * open-in-new-tab, which would start an authorization whose session lands in a
 * tab the user is not looking at. (It would also ignore `disabled`, whose
 * `:disabled` styling matches form controls only — but nothing passes `disabled`
 * a true value any more, so that is a reason waiting to matter rather than one
 * doing work today.)
 *
 * `location.assign`, not `replace`: Back from Google's consent screen should
 * return here rather than skip past the sign-in screen entirely.
 */
export function GoogleSignInButton({ disabled, children, className }: Props) {
  return (
    <button
      type="button"
      onClick={() => window.location.assign(SIGN_IN_START)}
      disabled={disabled}
      className={className}
    >
      {children}
    </button>
  );
}
