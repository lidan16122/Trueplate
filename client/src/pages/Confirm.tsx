import { useCallback, useMemo, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";

import { ConfidenceChip, ErrorNote, Eyebrow, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDayLabel, formatNumber, macroLine, MEAL_LABELS, MEAL_ORDER } from "@/lib/format";
import { scaleTo } from "@/lib/portion";
import type {
  FoodDetectionResponse,
  FoodEntryCreate,
  MealType,
  ResolvedFoodItem,
} from "@/types/api";

/** Local, editable copy of one proposed row. */
interface DraftItem {
  key: string;
  name: string;
  grams: number;
  /** Set true once the user edits the portion — their correction is a confirmation. */
  confirmed: boolean;
  item: ResolvedFoodItem;
}

const SURE_THRESHOLD = 0.75;

export function Confirm() {
  const navigate = useNavigate();
  const location = useLocation();
  const state = location.state as
    | { proposal?: FoodDetectionResponse; date?: string }
    | null;

  const proposal = state?.proposal;
  const date = state?.date ?? "";

  const [drafts, setDrafts] = useState<DraftItem[]>(() =>
    (proposal?.items ?? []).map((item, i) => ({
      key: `${i}-${item.detected.label}`,
      name: item.matched?.name ?? item.detected.label,
      grams: Math.round(item.detected.estimated_grams),
      confirmed: item.detected.confidence >= SURE_THRESHOLD,
      item,
    })),
  );
  const [meal, setMeal] = useState<MealType>(proposal?.meal_type ?? "dinner");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setGrams = useCallback((key: string, raw: string) => {
    const parsed = Number.parseFloat(raw);
    if (Number.isNaN(parsed)) return;
    setDrafts((prev) =>
      prev.map((d) =>
        d.key === key
          ? { ...d, grams: Math.max(1, Math.round(parsed)), confirmed: true }
          : d,
      ),
    );
  }, []);

  const removeItem = useCallback((key: string) => {
    setDrafts((prev) => prev.filter((d) => d.key !== key));
  }, []);

  const rows = useMemo(
    () =>
      drafts.map((draft) => {
        const match = draft.item.matched;
        // Recomputed from the per-100 g basis so the totals follow the moment a
        // portion is corrected — no stale numbers between edit and save.
        const calories = match ? scaleTo(draft.grams, match.kcal_per_100g) : 0;
        return {
          draft,
          calories,
          protein: match ? scaleTo(draft.grams, match.protein_g_per_100g) : 0,
          carbs: match ? scaleTo(draft.grams, match.carbs_g_per_100g) : 0,
          fat: match ? scaleTo(draft.grams, match.fat_g_per_100g) : 0,
        };
      }),
    [drafts],
  );

  const totals = useMemo(
    () =>
      rows.reduce(
        (acc, row) => ({
          calories: acc.calories + row.calories,
          protein: acc.protein + row.protein,
          carbs: acc.carbs + row.carbs,
          fat: acc.fat + row.fat,
        }),
        { calories: 0, protein: 0, carbs: 0, fat: 0 },
      ),
    [rows],
  );

  const roughCount = drafts.filter((d) => !d.confirmed).length;

  const save = useCallback(async () => {
    if (!proposal) return;
    setSaving(true);
    setError(null);
    try {
      const entries: FoodEntryCreate[] = drafts.flatMap((draft) => {
        const match = draft.item.matched;
        if (!match) return [];
        return [
          {
            name: draft.name,
            brand: match.brand,
            meal_type: meal,
            quantity_g: draft.grams,
            kcal_per_100g: match.kcal_per_100g,
            protein_g_per_100g: match.protein_g_per_100g,
            carbs_g_per_100g: match.carbs_g_per_100g,
            fat_g_per_100g: match.fat_g_per_100g,
            detection_method: proposal.kind,
            nutrition_source: match.source,
            source_ref: match.source_ref,
            // A corrected portion is confirmed; an untouched one keeps the
            // model's own confidence so the day view can still flag it.
            detection_confidence: draft.confirmed ? 1 : draft.item.detected.confidence,
            image_hash: proposal.image_hash,
          },
        ];
      });

      await api.logs.addEntries(date, entries);
      navigate(`/today${date ? `?date=${date}` : ""}`, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save these items");
      setSaving(false);
    }
  }, [proposal, drafts, meal, date, navigate]);

  // Reached directly, with nothing to confirm.
  if (!proposal) return <Navigate to="/add" replace />;

  return (
    <div className="flex min-h-dvh flex-col bg-page">
      <header className="flex items-center justify-between border-b border-line-2 bg-surface px-6 py-4 md:px-8">
        <div className="flex flex-col gap-1">
          <Eyebrow>{proposal.source_label}</Eyebrow>
          <span className="font-mono text-label text-faint">
            {formatDayLabel(date, true)}
          </span>
        </div>
        <button
          onClick={() => navigate("/add")}
          className="text-caption text-muted transition-colors hover:text-ink"
        >
          Cancel
        </button>
      </header>

      <main className="mx-auto w-full max-w-[760px] flex-1 px-6 py-6 md:px-8">
        {/* Meal selector */}
        <div className="flex flex-wrap gap-2">
          {MEAL_ORDER.map((option) => {
            const selected = option === meal;
            return (
              <button
                key={option}
                onClick={() => setMeal(option)}
                className={`h-10 rounded-card border px-4 text-body transition-colors ${
                  selected
                    ? "border-ink bg-ink text-white"
                    : "border-line bg-surface text-muted hover:border-ink"
                }`}
              >
                {MEAL_LABELS[option]}
              </button>
            );
          })}
        </div>

        {/* Items */}
        <ul className="mt-6 flex flex-col gap-3">
          {rows.map(({ draft, calories, protein, carbs, fat }) => (
            <li
              key={draft.key}
              className="flex items-start gap-4 rounded-lg border border-line bg-surface px-4 py-4"
            >
              <div className="flex min-w-0 flex-1 flex-col gap-2">
                <div className="truncate text-caption font-medium text-ink">{draft.name}</div>

                <div className="flex items-center gap-2">
                  <input
                    inputMode="numeric"
                    defaultValue={draft.grams}
                    onBlur={(e) => setGrams(draft.key, e.target.value)}
                    aria-label={`Grams of ${draft.name}`}
                    className="tabular h-10 w-20 rounded-card border border-line bg-surface px-3 text-center font-mono text-caption text-ink outline-none focus:border-accent"
                  />
                  <span className="text-caption text-subtle">g</span>
                  <ConfidenceChip
                    label={draft.confirmed ? "Fairly sure" : "Rough guess"}
                    isRough={!draft.confirmed}
                  />
                </div>

                <div className="tabular font-mono text-label text-subtle">
                  {macroLine(protein, carbs, fat, true)}
                </div>
              </div>

              <div className="flex flex-none flex-col items-end gap-2">
                <span className="tabular font-mono text-[17px] text-ink">
                  {formatNumber(calories)}
                </span>
                <button
                  onClick={() => removeItem(draft.key)}
                  aria-label={`Remove ${draft.name}`}
                  className="text-lead text-faint transition-colors hover:text-warn"
                >
                  ×
                </button>
              </div>
            </li>
          ))}
        </ul>

        {/* The nudge that makes correction feel expected rather than remedial. */}
        <p className="mt-4 text-caption leading-relaxed text-subtle">
          {roughCount === 0
            ? "Every portion confirmed."
            : `${roughCount} ${roughCount === 1 ? "portion is a rough guess" : "portions are rough guesses"} — tap the grams to correct ${roughCount === 1 ? "it" : "them"}.`}
        </p>

        {error && (
          <div className="mt-4">
            <ErrorNote>{error}</ErrorNote>
          </div>
        )}
      </main>

      <footer className="sticky bottom-0 border-t border-line-2 bg-surface px-6 py-5 md:px-8">
        <div className="mx-auto flex w-full max-w-[760px] items-center justify-between gap-6">
          <div className="flex flex-col gap-1">
            <Stat value={formatNumber(totals.calories)} size={28} />
            <span className="tabular font-mono text-label text-subtle">
              {macroLine(totals.protein, totals.carbs, totals.fat, true)}
            </span>
          </div>
          <button
            onClick={save}
            disabled={saving || drafts.length === 0}
            className="h-13 flex-1 rounded-lg bg-ink text-lead font-semibold text-white transition-colors hover:bg-accent disabled:opacity-40 md:max-w-[240px]"
          >
            {saving ? "Saving…" : "Add to log"}
          </button>
        </div>
      </footer>
    </div>
  );
}
