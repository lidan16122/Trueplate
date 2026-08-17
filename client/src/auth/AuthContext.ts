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
  refreshUser: () => Promise<void>;
}

export const AuthContext = createContext<AuthState | null>(null);
