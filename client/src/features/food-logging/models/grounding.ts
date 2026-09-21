import type { FoodDetectionResponse } from "@/types/detection";
import type { DraftItem } from "./draft";

/** A summary describes the server's original portions and matches, so edits invalidate it. */
export function hasOriginalNutrition(proposal: FoodDetectionResponse, drafts: DraftItem[]): boolean {
  return drafts.length === proposal.items.length && drafts.every((draft, index) => {
    const item = proposal.items[index];
    return draft.detected === item.detected && draft.matched === item.matched &&
      draft.grams === item.detected.estimated_grams;
  });
}
