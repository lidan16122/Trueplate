import { useCallback, useEffect, useMemo, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";

import { ErrorNote, Eyebrow } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { formatDayLabel, formatNumber, macroLine, MEAL_LABELS, MEAL_ORDER } from "@/lib/format";
import { scaleTo } from "@/lib/portion";
import type {
  DetectedFood,
  FoodDetectionResponse,
  FoodEntryCreate,
  MealType,
  NutritionMatch,
  ResolvedFoodItem,
} from "@/types/api";

/** Local, editable copy of one proposed row. */
interface DraftItem {
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
  unit: string | null;
}

const SURE_THRESHOLD = 0.75;

const KIND_LABEL: Record<string, string> = {
  photo: "Photo",
  text: "Description",
  barcode: "Barcode",
  manual: "Manual",
};

function toDraft(item: ResolvedFoodItem, index: number): DraftItem {
  const { detected } = item;
  const quantity = detected.household_quantity;
  return {
    key: `${index}-${detected.label}`,
    name: item.matched?.name ?? detected.label,
    grams: Math.round(detected.estimated_grams),
    confirmed: !item.is_rough && detected.confidence >= SURE_THRESHOLD,
    matched: item.matched,
    alternatives: item.alternatives,
    detected,
    gramsPerUnit: quantity && quantity > 0 ? detected.estimated_grams / quantity : null,
    unit: detected.household_unit,
  };
}

export function Confirm() {
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
              name: alternative.name,
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
      const found = await api.ai.detectText(addText);
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
            serving_description:
              units && draft.unit ? `${Number(units.toFixed(2))} ${draft.unit}` : null,
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

      await api.logs.addEntries(date, entries);
      navigate(`/today${date ? `?date=${date}` : ""}`, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save these items");
      setSaving(false);
    }
  }, [proposal, drafts, meal, date, navigate]);

  // Reached directly, with nothing to confirm.
  if (!proposal) return <Navigate to="/add" replace />;

  const sourceNote = `${proposal.source_label}. Trueplate estimated the portions — the calorie numbers come from the food database once the grams are right.`;
  const roughNote =
    roughCount === 0
      ? "Every portion confirmed."
      : `${roughCount} ${roughCount === 1 ? "portion is a rough guess" : "portions are rough guesses"} — tap the grams to correct ${roughCount === 1 ? "it" : "them"}.`;

  const photoPanel = (
    <div className="flex h-full w-full items-center justify-center overflow-hidden rounded-lg border border-dashed border-hairline bg-placeholder">
      {photo ? (
        <img src={photo} alt="" className="h-full w-full object-cover" />
      ) : (
        <span className="font-mono text-micro tracking-[0.08em] text-faint">MEAL PHOTO</span>
      )}
    </div>
  );

  const mealPicker = (height: string) => (
    <div className="flex gap-1.5">
      {MEAL_ORDER.map((option) => {
        const selected = option === meal;
        return (
          <button
            key={option}
            onClick={() => setMeal(option)}
            className={`flex-1 rounded-md border text-caption font-medium transition-colors ${height} ${
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
  );

  const confidence = (draft: DraftItem) => (
    <div className="flex items-center gap-2">
      <span
        className={`h-1.5 w-1.5 flex-none rounded-full ${draft.confirmed ? "bg-accent" : "bg-warn"}`}
      />
      <span className={`text-label ${draft.confirmed ? "text-accent" : "text-warn"}`}>
        {draft.matched === null
          ? "No match — edit or remove"
          : draft.confirmed
            ? "Fairly sure"
            : "Rough guess"}
      </span>
      {draft.alternatives.length > 0 && (
        <button
          onClick={() => setOpenAlts(openAlts === draft.key ? null : draft.key)}
          className="text-label text-faint underline-offset-2 transition-colors hover:text-ink hover:underline"
        >
          {openAlts === draft.key ? "close" : "not right?"}
        </button>
      )}
    </div>
  );

  const alternatives = (draft: DraftItem) =>
    openAlts === draft.key && (
      <div className="flex flex-col gap-1 rounded-card border border-line-card bg-panel p-2">
        {draft.alternatives.slice(0, 4).map((alt) => (
          <button
            key={`${alt.source}-${alt.source_ref}-${alt.name}`}
            onClick={() => swapMatch(draft.key, alt)}
            className="flex items-baseline justify-between gap-3 rounded-chip px-2 py-1.5 text-left transition-colors hover:bg-wash"
          >
            <span className="min-w-0 truncate text-caption text-ink">{alt.name}</span>
            <span className="tabular flex-none font-mono text-micro text-faint">
              {formatNumber(alt.kcal_per_100g)} /100g
            </span>
          </button>
        ))}
      </div>
    );

  const gramsInput = (draft: DraftItem, width: string, height: string, size: string) => (
    <div className={`relative flex flex-none items-center ${width}`}>
      <input
        inputMode="numeric"
        value={draft.grams}
        onChange={(e) => setGrams(draft.key, e.target.value)}
        aria-label={`Grams of ${draft.name}`}
        className={`tabular w-full rounded-md border border-line-control bg-surface pr-8 pl-3.5 font-mono text-ink outline-none focus:border-accent ${height} ${size}`}
      />
      <span className="pointer-events-none absolute right-3.5 text-caption text-faint">g</span>
    </div>
  );

  const householdInput = (draft: DraftItem, value: number | null) =>
    value !== null &&
    draft.unit && (
      <div className="flex items-center gap-1.5">
        <input
          inputMode="decimal"
          value={Number(value.toFixed(2))}
          onChange={(e) => setHousehold(draft.key, e.target.value)}
          aria-label={`${draft.unit} of ${draft.name}`}
          className="tabular h-7 w-14 rounded-chip border border-line-control bg-surface px-2 text-center font-mono text-label text-ink outline-none focus:border-accent"
        />
        <span className="text-label text-subtle">{draft.unit}</span>
      </div>
    );

  const addRow = (
    <>
      {adding ? (
        <div className="flex gap-2">
          <input
            autoFocus
            value={addText}
            onChange={(e) => setAddText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void addMissed()}
            placeholder="a slice of bread with butter"
            className="h-12 min-w-0 flex-1 rounded-lg border border-line px-4 text-body text-ink outline-none placeholder:text-faint focus:border-accent"
          />
          <button
            onClick={addMissed}
            disabled={addBusy || addText.trim().length < 2}
            className="h-12 flex-none rounded-lg bg-ink px-4 text-body font-medium text-white transition-colors hover:bg-accent disabled:opacity-40"
          >
            {addBusy ? "Finding…" : "Find"}
          </button>
        </div>
      ) : (
        <button
          onClick={() => setAdding(true)}
          className="h-12 w-full rounded-lg border border-dashed border-hairline text-body font-medium text-muted transition-colors hover:border-ink hover:text-ink"
        >
          + Add a missed item
        </button>
      )}
    </>
  );

  const footerTotals = (size: string) => (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-baseline gap-2">
        <span
          className={`tabular font-mono font-medium text-ink ${size}`}
        >
          {formatNumber(totals.calories)}
        </span>
        <span className="text-caption text-subtle">kcal total</span>
      </div>
      <span className="tabular font-mono text-label text-faint">
        {macroLine(totals.protein, totals.carbs, totals.fat, true)}
      </span>
    </div>
  );

  return (
    <>
      {/* ============================ MOBILE ============================ */}
      <div className="flex min-h-dvh flex-col bg-surface md:hidden">
        <header className="flex h-13 flex-none items-center justify-between border-b border-line-2 pr-5 pl-4">
          <button
            onClick={() => navigate("/add")}
            aria-label="Back"
            className="flex h-9 w-9 items-center justify-center rounded-full text-lead text-muted transition-colors hover:bg-wash hover:text-ink"
          >
            ←
          </button>
          <span className="text-[15px] font-semibold text-ink">Check before saving</span>
          <span className="tabular font-mono text-label text-faint">
            {formatDayLabel(date, true)}
          </span>
        </header>

        <main className="flex flex-1 flex-col gap-4.5 overflow-auto px-5 pt-4 pb-[150px]">
          <div className="h-[150px] flex-none">{photoPanel}</div>
          <p className="text-caption leading-relaxed text-subtle">{sourceNote}</p>

          <div className="flex flex-col gap-2">
            {rows.map(({ draft, calories, protein, carbs, fat, household }) => (
              <div
                key={draft.key}
                className="flex flex-col gap-2.5 rounded-lg border border-line-card p-3.5"
              >
                <div className="flex items-start gap-2.5">
                  <span className="min-w-0 flex-1 text-lead font-semibold break-words text-ink">
                    {draft.name}
                  </span>
                  <button
                    onClick={() => removeItem(draft.key)}
                    aria-label={`Remove ${draft.name}`}
                    className="-mt-1 -mr-1 flex h-7 w-7 flex-none items-center justify-center rounded-full text-lead text-icon-faint transition-colors hover:bg-wash hover:text-ink"
                  >
                    ×
                  </button>
                </div>

                <div className="flex items-center gap-2.5">
                  {gramsInput(draft, "w-[118px]", "h-11.5", "text-[19px]")}
                  <div className="flex flex-1 flex-col items-end gap-0.5">
                    <span className="tabular font-mono text-[19px] text-ink">
                      {formatNumber(calories)} kcal
                    </span>
                    <span className="tabular font-mono text-micro text-faint">
                      {macroLine(protein, carbs, fat, true)}
                    </span>
                  </div>
                </div>

                <div className="flex items-center justify-between gap-2">
                  {confidence(draft)}
                  {householdInput(draft, household)}
                </div>
                {alternatives(draft)}
              </div>
            ))}
            {addRow}
          </div>

          <div className="flex flex-col gap-2">
            <Eyebrow>Meal</Eyebrow>
            {mealPicker("h-10.5")}
          </div>

          <p className="text-label leading-relaxed text-subtle">{roughNote}</p>
          {unresolved > 0 && (
            <p className="text-label leading-relaxed text-warn">
              {unresolved} item{unresolved === 1 ? "" : "s"} could not be matched to a food and
              will not be saved.
            </p>
          )}
          {error && <ErrorNote>{error}</ErrorNote>}
        </main>

        <footer className="fixed inset-x-0 bottom-0 flex flex-col gap-3 border-t border-line-2 bg-surface px-5 pt-3.5 pb-7">
          <div className="flex items-baseline justify-between">{footerTotals("text-[26px]")}</div>
          <button
            onClick={save}
            disabled={saving || drafts.length === 0}
            className="h-14 w-full rounded-lg bg-ink text-lead font-semibold text-white transition-colors hover:bg-accent disabled:opacity-40"
          >
            {saving ? "Saving…" : "Confirm and save"}
          </button>
        </footer>
      </div>

      {/* =========================== DESKTOP ============================ */}
      <div className="hidden h-dvh flex-col bg-surface md:flex">
        <header className="flex h-16 flex-none items-center justify-between border-b border-line-2 px-8">
          <div className="flex items-center gap-3.5">
            <button
              onClick={() => navigate("/add")}
              className="text-body text-muted transition-colors hover:text-ink"
            >
              ← Back
            </button>
            <span className="text-lead font-semibold text-ink">Check before saving</span>
          </div>
          <span className="tabular font-mono text-caption text-faint">
            {KIND_LABEL[proposal.kind] ?? proposal.kind} · {formatDayLabel(date, true)}
          </span>
        </header>

        <div className="flex min-h-0 flex-1">
          <div className="flex w-[480px] flex-none flex-col gap-4 p-8">
            <div className="min-h-0 flex-1">{photoPanel}</div>
            <p className="flex-none text-caption leading-relaxed text-subtle">{sourceNote}</p>
          </div>

          <div className="flex min-w-0 flex-1 flex-col border-l border-line-2">
            <div className="flex flex-1 flex-col gap-2.5 overflow-auto p-8">
              {rows.map(({ draft, calories, protein, carbs, fat, household }) => (
                <div
                  key={draft.key}
                  className="flex flex-col gap-2 rounded-card border border-line-card px-4 py-3.5"
                >
                  <div className="flex items-center gap-4">
                    <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                      <span className="truncate text-lead font-semibold text-ink">
                        {draft.name}
                      </span>
                      {confidence(draft)}
                    </div>

                    {householdInput(draft, household)}
                    {gramsInput(draft, "w-[104px]", "h-11", "text-[17px]")}

                    <div className="flex w-[118px] flex-none flex-col items-end gap-0.5">
                      <span className="tabular font-mono text-[17px] text-ink">
                        {formatNumber(calories)}
                      </span>
                      <span className="tabular font-mono text-micro text-faint">
                        {macroLine(protein, carbs, fat, true)}
                      </span>
                    </div>

                    <button
                      onClick={() => removeItem(draft.key)}
                      aria-label={`Remove ${draft.name}`}
                      className="flex h-7 w-7 flex-none items-center justify-center rounded-full text-lead text-icon-faint transition-colors hover:bg-page hover:text-ink"
                    >
                      ×
                    </button>
                  </div>
                  {alternatives(draft)}
                </div>
              ))}

              {addRow}

              <div className="flex items-center gap-3 pt-2">
                <Eyebrow>Meal</Eyebrow>
                <div className="flex-1">{mealPicker("h-10")}</div>
              </div>

              <p className="text-caption leading-relaxed text-subtle">{roughNote}</p>
              {unresolved > 0 && (
                <p className="text-caption leading-relaxed text-warn">
                  {unresolved} item{unresolved === 1 ? "" : "s"} could not be matched to a food and
                  will not be saved.
                </p>
              )}
              {error && <ErrorNote>{error}</ErrorNote>}
            </div>

            <div className="flex flex-none items-center justify-between gap-5 border-t border-line-2 px-8 py-4.5">
              {footerTotals("text-[28px]")}
              <button
                onClick={save}
                disabled={saving || drafts.length === 0}
                className="h-13 flex-none rounded-card bg-ink px-8 text-lead font-semibold text-white transition-colors hover:bg-accent disabled:opacity-40"
              >
                {saving ? "Saving…" : "Confirm and save"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
