import type { Profile, PromptLimit, Targets } from "@/types/profile";

import { get, patch } from "@/services/http";

export const profileApi = {
    read: () => get<Profile>("/profile"),
    update: (payload: Record<string, unknown>) => patch<Targets>("/profile", payload),
    targets: () => get<Targets>("/profile/targets"),
    /** How much of the account's AI-detection allowance is left. */
    userLimit: () => get<PromptLimit>("/profile/user-limit"),
  };
