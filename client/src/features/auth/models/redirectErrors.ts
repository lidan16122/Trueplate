

// The server's failure vocabulary for the redirect flow, turned into something a
// person can act on. Sign-in leaves the page entirely now, so a failure returns
// the user to a screen identical to the one they left — silent, which is exactly
// the state three earlier attempts at this bug left the app in.
//
// Mapped, never rendered raw. The query param is whatever is in the address bar;
// React escapes it so it is not XSS, but echoing it would let a crafted link
// print arbitrary text inside our own chrome — a convincing place to leave a
// phone number. Anything unrecognised renders nothing.
export const REDIRECT_ERRORS: Record<string, string | undefined> = {
  state: "That sign-in attempt expired or was interrupted. Please try again.",
  google: "Google did not finish the sign-in.",
  exchange: "Could not reach Google to finish signing in. Please try again.",
  verification: "Google sign-in could not be verified.",
  email_in_use: "That email is already registered with a different sign-in method.",
  unavailable: "Google sign-in is unavailable right now.",
};
