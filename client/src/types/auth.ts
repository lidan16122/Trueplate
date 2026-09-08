export interface User {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  avatar_url: string | null;
  full_name: string;
  initials: string;
}

/** Returned by both `POST /auth/google` and `GET /auth/me` — one shape, so
 *  sign-in and a cold reload cannot disagree about where a user belongs. */
export interface SessionResponse {
  user: User;
  needs_onboarding: boolean;
}

export interface Session {
  family_id: string;
  device_label: string;
  ip: string;
  created_at: string;
  last_used_at: string;
  is_current: boolean;
}
