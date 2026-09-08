import type { DetectionMethod } from "./detection";
import type { MealType } from "./meals";
import type { NutritionFacts, NutritionSource } from "./nutrition";

export interface FoodEntry {
  id: string;
  name: string;
  brand: string | null;
  meal_type: MealType;
  quantity_g: number;
  /** The portion as the user entered it — "1 cup", "1 bar". Display only. */
  serving_description: string | null;
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
  /** Household form of the portion ("1.5 cups"). Display only — grams rule. */
  serving_description?: string | null;
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
