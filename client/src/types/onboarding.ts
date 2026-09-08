import type { GoalType, Sex } from "./profile";

export interface OnboardingPayload {
  /** Prefilled from Google and confirmed in the wizard, so a correction saves
   *  in the same request as every other answer. */
  first_name?: string;
  last_name?: string;
  age: number;
  sex: Sex;
  height_cm: number;
  weight_kg: number;
  goal_type: GoalType;
  target_weight_kg?: number | null;
  rate_kg_per_week?: number;
  timezone?: string;
}
