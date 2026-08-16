import { createContext } from "react";

import type { User } from "@/types/api";

export interface AuthState {
  user: User | null;
  /** True until the initial "am I signed in?" check settles. */
  isLoading: boolean;
  signIn: (credential: string) => Promise<{ needsOnboarding: boolean }>;
  signOut: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

export const AuthContext = createContext<AuthState | null>(null);
