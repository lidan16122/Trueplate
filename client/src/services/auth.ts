import type { SessionResponse } from "@/types/auth";

import { del, get, post } from "@/services/http";

export const authApi = {
    /** `skipRefresh`: a failure here means bad credentials, not a stale session. */
    signInWithGoogle: (credential: string) =>
      post<SessionResponse>("/auth/google", { credential }, { skipRefresh: true }),
    me: () => get<SessionResponse>("/auth/me"),
    logout: () => post<{ detail: string }>("/auth/logout", undefined, { skipRefresh: true }),
    revokeSession: (familyId: string) => del<{ detail: string }>(`/auth/sessions/${familyId}`),
  };
