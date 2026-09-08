import type { MealType } from "./meals";
import type { HouseholdUnit, NutritionFacts, NutritionMatch } from "./nutrition";

export type DetectionMethod = "photo" | "text" | "barcode" | "manual";

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
  /**
   * A familiar handle on the same mass — "1.5 cups", "2 slices".
   *
   * Grams stay authoritative. The ratio `estimated_grams / household_quantity`
   * is the grams-per-unit for this food in this photo, so editing the familiar
   * number rescales grams by the model's own anchor. That is why there is no
   * density table anywhere: we never convert between units, only within one.
   *
   * Both are null for foods with no natural unit — a smear of sauce is not
   * "1" of anything.
   */
  household_quantity: number | null;
  household_unit: HouseholdUnit | null;
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
  /** What the model said it saw, in its own words, before it listed anything. */
  meal_description: string;
  items: ResolvedFoodItem[];
  totals: NutritionFacts;
  image_hash: string | null;
  cached: boolean;
  /** The server doubts this reading and did not cache it, so resubmitting retries. */
  is_provisional: boolean;
  notes: string | null;
}
