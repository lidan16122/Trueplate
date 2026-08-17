import { createContext } from "react";

import type { User } from "@/types/api";

export interface AuthState {
  user: User | null;
  /** True until the initial "am I signed in?" check settles. */
  isLoading: boolean;
  /**
   * Whether the wizard is still outstanding, straight from the server on every
   * session read. Held here rather than derived at the sign-in call site, so a
   * hard refresh reaches the same answer as a fresh sign-in.
   */
  needsOnboarding: boolean;
  signIn: (credential: string) => Promise<void>;
  signOut: () => Promise<void>;
  /**
   * Clear the onboarding requirement after the wizard has been saved.
   *
   * Local and synchronous by design. A successful `POST /onboarding` already
   * proves the profile and goal exist, so re-reading the session to learn it
   * only adds a way to fail — and `refreshUser` treats any failure as a lost
   * session, which would sign the user out the instant they finished.
   */
  completeOnboarding: () => void;
  refreshUser: () => Promise<void>;
}

export const AuthContext = createContext<AuthState | null>(null);
