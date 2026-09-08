export type NutritionSource = "usda_fdc" | "open_food_facts" | "seed" | "manual";

export interface NutritionFacts {
  calories: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
}

/** Mirrors the closed set on the server; widening it here loses the check. */
export type HouseholdUnit =
  | "cup"
  | "tbsp"
  | "tsp"
  | "slice"
  | "piece"
  | "medium"
  | "small"
  | "large"
  | "bowl"
  | "plate"
  | "glass"
  | "can"
  | "bottle"
  | "scoop"
  | "handful"
  | "fillet"
  | "egg";

export interface NutritionMatch {
  food_id: string | null;
  name: string;
  brand: string | null;
  source: NutritionSource;
  source_ref: string | null;
  /** The label's own serving ("1 bar (40 g)"). Barcode products only. */
  serving_description: string | null;
  kcal_per_100g: number;
  protein_g_per_100g: number;
  carbs_g_per_100g: number;
  fat_g_per_100g: number;
}
