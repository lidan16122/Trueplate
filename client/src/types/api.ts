/** Mirrors of the server's Pydantic schemas. Keep in step with `server/app/schemas`. */

export type Sex = "female" | "male";
export type GoalType = "lose" | "maintain" | "gain";
export type MealType = "breakfast" | "lunch" | "dinner" | "snack";
export type DetectionMethod = "photo" | "text" | "barcode" | "manual";
export type NutritionSource = "usda_fdc" | "open_food_facts" | "seed" | "manual";

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

export interface OnboardingPayload {
  age: number;
  sex: Sex;
  height_cm: number;
  weight_kg: number;
  goal_type: GoalType;
  target_weight_kg?: number | null;
  rate_kg_per_week?: number;
  timezone?: string;
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

export interface NutritionFacts {
  calories: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
}

export interface FoodEntry {
  id: string;
  name: string;
  brand: string | null;
  meal_type: MealType;
  quantity_g: number;
  calories: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  detection_method: DetectionMethod;
  nutrition_source: NutritionSource;
  detection_confidence: number | null;
  /** "Fairly sure" | "Rough guess" — resolved server-side. */
  confidence_label: string | null;
  is_rough: boolean;
}

export interface MealGroup {
  meal_type: MealType;
  calories: number;
  entries: FoodEntry[];
}

export interface DayLog {
  log_date: string;
  groups: MealGroup[];
  totals: NutritionFacts;
  target_calories: number | null;
  target_protein_g: number | null;
  target_carbs_g: number | null;
  target_fat_g: number | null;
}

export interface DaySummary {
  log_date: string;
  calories: number;
  has_entries: boolean;
}

export interface FoodEntryCreate {
  name: string;
  brand?: string | null;
  meal_type: MealType;
  quantity_g: number;
  kcal_per_100g: number;
  protein_g_per_100g: number;
  carbs_g_per_100g: number;
  fat_g_per_100g: number;
  detection_method: DetectionMethod;
  nutrition_source: NutritionSource;
  source_ref?: string | null;
  detection_confidence?: number | null;
  image_hash?: string | null;
}

/**
 * One row of the confirmation screen.
 *
 * Note there is no nutrition on `detected` — the model contributes a label and
 * a mass, and `nutrition` is what the server computed from the database match.
 */
export interface DetectedFood {
  label: string;
  estimated_grams: number;
  confidence: number;
  preparation: string;
  search_terms: string[];
  portion_reasoning: string | null;
}

export interface NutritionMatch {
  food_id: string | null;
  name: string;
  brand: string | null;
  source: NutritionSource;
  source_ref: string | null;
  kcal_per_100g: number;
  protein_g_per_100g: number;
  carbs_g_per_100g: number;
  fat_g_per_100g: number;
}

export interface ResolvedFoodItem {
  detected: DetectedFood;
  matched: NutritionMatch | null;
  nutrition: NutritionFacts;
  alternatives: NutritionMatch[];
  confidence_label: string;
  is_rough: boolean;
}

export interface FoodDetectionResponse {
  detection_id: string;
  kind: DetectionMethod;
  source_label: string;
  meal_type: MealType;
  items: ResolvedFoodItem[];
  totals: NutritionFacts;
  image_hash: string | null;
  cached: boolean;
  notes: string | null;
}
