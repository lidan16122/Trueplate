export interface User {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  avatar_url: string | null;
  full_name: string;
  initials: string;
}

/** Shared by sign-in, `/auth/me`, and authenticated `/auth/session` results.
 *  The same onboarding state keeps sign-in and reload routing consistent. */
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
