import { scaleTo } from "@/models/nutrition";
import { ApiError } from "@/services/http";
import type { FoodDetectionResponse } from "@/types/detection";
import type { FoodEntryCreate } from "@/types/logs";
import type { MealType } from "@/types/meals";
import type { NutritionMatch } from "@/types/nutrition";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { toDraft, type DraftItem } from "../models/draft";
import { detectionApi } from "../services/detection";
import { logsApi } from "../services/logs";


/** Keeps editable portions and their save payload in one workflow so corrections reach the food log. */
export function useConfirm() {
  const navigate = useNavigate();
  const location = useLocation();
  const state = location.state as
    | { proposal?: FoodDetectionResponse; date?: string; photo?: string | null }
    | null;

  const proposal = state?.proposal;
  const date = state?.date ?? "";
  const photo = state?.photo ?? null;

  const [drafts, setDrafts] = useState<DraftItem[]>(() => (proposal?.items ?? []).map(toDraft));
  const [meal, setMeal] = useState<MealType>(proposal?.meal_type ?? "dinner");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [addText, setAddText] = useState("");
  const [addBusy, setAddBusy] = useState(false);
  const [openAlts, setOpenAlts] = useState<string | null>(null);

  // AddFood created this object URL and handed ownership over; releasing it is
  // ours to do, or the blob outlives the screen that shows it.
  useEffect(
    () => () => {
      if (photo) URL.revokeObjectURL(photo);
    },
    [photo],
  );

  const setGrams = useCallback((key: string, raw: string) => {
    const parsed = Number.parseFloat(raw);
    if (Number.isNaN(parsed)) return;
    setDrafts((prev) =>
      prev.map((d) =>
        d.key === key ? { ...d, grams: Math.max(1, Math.round(parsed)), confirmed: true } : d,
      ),
    );
  }, []);

  /** Editing "1.5 cups" rescales grams by the model's own grams-per-unit. */
  const setHousehold = useCallback((key: string, raw: string) => {
    const parsed = Number.parseFloat(raw);
    if (Number.isNaN(parsed) || parsed <= 0) return;
    setDrafts((prev) =>
      prev.map((d) =>
        d.key === key && d.gramsPerUnit
          ? { ...d, grams: Math.max(1, Math.round(parsed * d.gramsPerUnit)), confirmed: true }
          : d,
      ),
    );
  }, []);

  const swapMatch = useCallback((key: string, alternative: NutritionMatch) => {
    setDrafts((prev) =>
      prev.map((d) =>
        d.key === key
          ? {
              ...d,
              matched: alternative,
              // The *source* changes, not the food's name. `name` is what goes
              // into `food_entries.name`, which the resolver reserves for the
              // user's own words — overwriting it with "Chicken, broilers or
              // fryers, leg, meat and skin, cooked, roasted" puts database
              // wording in the food log for good. The swapped row stays visible
              // on the provenance line directly beneath.
              // Picking the right food by hand settles it; the warning has done
              // its job and should stop nagging.
              confirmed: true,
              alternatives: [d.matched, ...d.alternatives].filter(
                (m): m is NutritionMatch => m !== null && m.name !== alternative.name,
              ),
            }
          : d,
      ),
    );
    setOpenAlts(null);
  }, []);

  const removeItem = useCallback((key: string) => {
    setDrafts((prev) => prev.filter((d) => d.key !== key));
  }, []);

  const addMissed = useCallback(async () => {
    if (addText.trim().length < 2) return;
    setAddBusy(true);
    setError(null);
    try {
      const found = await detectionApi.detectText(addText);
      setDrafts((prev) => [
        ...prev,
        ...found.items.map((item, i) => toDraft(item, prev.length + i)),
      ]);
      setAddText("");
      setAdding(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not find that item");
    } finally {
      setAddBusy(false);
    }
  }, [addText]);

  const rows = useMemo(
    () =>
      drafts.map((draft) => {
        const m = draft.matched;
        // Recomputed from the per-100 g basis so the totals follow the moment a
        // portion is corrected — no stale numbers between edit and save.
        return {
          draft,
          calories: m ? scaleTo(draft.grams, m.kcal_per_100g) : 0,
          protein: m ? scaleTo(draft.grams, m.protein_g_per_100g) : 0,
          carbs: m ? scaleTo(draft.grams, m.carbs_g_per_100g) : 0,
          fat: m ? scaleTo(draft.grams, m.fat_g_per_100g) : 0,
          household: draft.gramsPerUnit ? draft.grams / draft.gramsPerUnit : null,
        };
      }),
    [drafts],
  );

  const totals = useMemo(
    () =>
      rows.reduce(
        (acc, r) => ({
          calories: acc.calories + r.calories,
          protein: acc.protein + r.protein,
          carbs: acc.carbs + r.carbs,
          fat: acc.fat + r.fat,
        }),
        { calories: 0, protein: 0, carbs: 0, fat: 0 },
      ),
    [rows],
  );

  const roughCount = drafts.filter((d) => !d.confirmed).length;
  const unresolved = drafts.filter((d) => d.matched === null).length;

  const save = useCallback(async () => {
    if (!proposal) return;
    setSaving(true);
    setError(null);
    try {
      const entries: FoodEntryCreate[] = drafts.flatMap((draft) => {
        const m = draft.matched;
        if (!m) return [];
        const units = draft.gramsPerUnit ? draft.grams / draft.gramsPerUnit : null;
        return [
          {
            name: draft.name,
            brand: m.brand,
            meal_type: meal,
            quantity_g: draft.grams,
            // So the day view can read "1 cup rice" rather than "158 g rice".
            // A scanned product has no household unit for the model to have
            // estimated, but it does have the serving printed on the label —
            // prefer that, so a barcode entry reads "1 bar (40 g)".
            serving_description:
              units && draft.unit
                ? `${Number(units.toFixed(2))} ${draft.unit}`
                : (m.serving_description ?? null),
            kcal_per_100g: m.kcal_per_100g,
            protein_g_per_100g: m.protein_g_per_100g,
            carbs_g_per_100g: m.carbs_g_per_100g,
            fat_g_per_100g: m.fat_g_per_100g,
            detection_method: proposal.kind,
            nutrition_source: m.source,
            source_ref: m.source_ref,
            // A corrected portion is confirmed; an untouched one keeps the
            // model's own confidence so the day view can still flag it.
            detection_confidence: draft.confirmed ? 1 : draft.detected.confidence,
            image_hash: proposal.image_hash,
          },
        ];
      });

      await logsApi.addEntries(date, entries);
      navigate(`/today${date ? `?date=${date}` : ""}`, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save these items");
      setSaving(false);
    }
  }, [proposal, drafts, meal, date, navigate]);


  return {
    navigate,
    proposal,
    date,
    photo,
    drafts,
    meal,
    setMeal,
    saving,
    error,
    adding,
    setAdding,
    addText,
    setAddText,
    addBusy,
    openAlts,
    setOpenAlts,
    setGrams,
    setHousehold,
    swapMatch,
    removeItem,
    addMissed,
    rows,
    totals,
    roughCount,
    unresolved,
    save,
  };
}
