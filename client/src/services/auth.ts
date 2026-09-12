import type { SessionResponse } from "@/types/auth";

import { ApiError, del, get, post } from "@/services/http";

export const authApi = {
    /** `skipRefresh`: a failure here means bad credentials, not a stale session. */
    signInWithGoogle: (credential: string) =>
      post<SessionResponse>("/auth/google", { credential }, { skipRefresh: true }),
    /** Anonymous startup is a normal result; expired access still uses the shared refresh. */
    session: async () => {
      try {
        return await get<SessionResponse | null>("/auth/session");
      } catch (error) {
        // Client and API deployments finish independently, so an older API may still be serving.
        if (error instanceof ApiError && error.status === 404) {
          return get<SessionResponse>("/auth/me");
        }
        throw error;
      }
    },
    me: () => get<SessionResponse>("/auth/me"),
    logout: () => post<{ detail: string }>("/auth/logout", undefined, { skipRefresh: true }),
    revokeSession: (familyId: string) => del<{ detail: string }>(`/auth/sessions/${familyId}`),
  };
