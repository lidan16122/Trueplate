/** Mirrors of the server's Pydantic schemas. Keep in step with `server/app/schemas`. */

export type Sex = "female" | "male";

export type GoalType = "lose" | "maintain" | "gain";

export interface MathRow {
  label: string;
  value: string;
}

export interface Targets {
  bmr: number;
  activity_factor: number;
  tdee: number;
  delta: number;
  target_calories: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  goal_type: GoalType;
  rate_kg_per_week: number;
  target_weight_kg: number;
  weeks_to_target: number;
  /** The reveal screen shows its working; these are those lines. */
  math_rows: MathRow[];
  summary: string;
}

export interface PromptLimit {
  allowed: boolean;
  used: number;
  /** Null for an uncapped account, which is what a null `max_prompts` means. */
  limit: number | null;
}

export interface Profile {
  age: number | null;
  sex: Sex | null;
  height_cm: number | null;
  weight_kg: number | null;
  activity_level: string;
  unit_preference: string;
  timezone: string;
}
