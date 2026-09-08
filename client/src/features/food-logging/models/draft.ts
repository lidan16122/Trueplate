import type { DetectedFood, ResolvedFoodItem } from "@/types/detection";
import type { HouseholdUnit, NutritionMatch } from "@/types/nutrition";


/** Local, editable copy of one proposed row. */
export interface DraftItem {
  key: string;
  name: string;
  grams: number;
  /** Set true once the user edits the portion — their correction is a confirmation. */
  confirmed: boolean;
  matched: NutritionMatch | null;
  alternatives: NutritionMatch[];
  detected: DetectedFood;
  /**
   * Grams per household unit, from the model's own estimate for *this* food.
   *
   * Null when the food has no natural unit. This is the whole trick that avoids
   * a density table: we never convert between units, only scale within the one
   * the model already anchored to a gram figure.
   */
  gramsPerUnit: number | null;
  unit: HouseholdUnit | null;
  /**
   * The server's own wording for how sure it is.
   *
   * Taken rather than re-derived: the threshold that turns a confidence float
   * into two words lives in `schemas/log.py`, and a second copy here would let
   * the confirm screen and the day view disagree about the same entry.
   */
  serverLabel: string;
}


export function toDraft(item: ResolvedFoodItem, index: number): DraftItem {
  const { detected } = item;
  const quantity = detected.household_quantity;
  return {
    key: `${index}-${detected.label}`,
    // The model's own wording, not the row it resolved to. A USDA name is
    // written for a database ("Rice, white, long-grain, regular, cooked,
    // enriched, with salt") and reads as noise on a plate of food; the match
    // still shows, one line down, as provenance. This is also what makes
    // `food_entries.name` the user's language, which `resolver.py` already
    // documents as the intent while this line quietly overrode it.
    name: detected.label,
    grams: Math.round(detected.estimated_grams),
    confirmed: !item.is_rough,
    matched: item.matched,
    alternatives: item.alternatives,
    detected,
    gramsPerUnit: quantity && quantity > 0 ? detected.estimated_grams / quantity : null,
    unit: detected.household_unit,
    serverLabel: item.confidence_label,
  };
}
