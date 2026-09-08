import type { OnboardingPayload } from "@/types/onboarding";
import type { Targets } from "@/types/profile";

import { post } from "@/services/http";

export const onboardingApi = {
    complete: (payload: OnboardingPayload) =>
      post<{ targets: Targets }>("/onboarding", payload),
    /** Live target preview while the wizard is still being filled in. */
    preview: (payload: OnboardingPayload) => post<Targets>("/onboarding/preview", payload),
  };
