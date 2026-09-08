import { Navigate } from "react-router";
import { useConfirm } from "../hooks/useConfirm";
import { type DraftItem } from "../models/draft";

import { ErrorNote } from "@/components/ErrorNote";
import { Eyebrow } from "@/components/Eyebrow";
import { Stat } from "@/components/Stat";
import { MEAL_LABELS, MEAL_ORDER } from "@/models/meals";
import { formatDayLabel, formatNumber, macroLine } from "@/utils/format";

const KIND_LABEL: Record<string, string> = {
  photo: "Photo",
  text: "Description",
  barcode: "Barcode",
  manual: "Manual",
};

export function Confirm() {
  const {
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
  } = useConfirm();

  // Reached directly, with nothing to confirm.
  if (!proposal) return <Navigate to="/add" replace />;

  const sourceNote =
    `${proposal.source_label}. Trueplate estimated the portions — the calorie numbers ` +
    "come from the food database once the grams are right." +
    // `cached` existed to tell the user a reading cost nothing and is not a
    // fresh look at the plate, and was never shown.
    (proposal.cached ? " Recognised from an earlier reading of this photo." : "");

  // The model's own inventory, above the list it produced from it. When a plate
  // of five things comes back as one row, this line is the only thing on screen
  // that says so — and "+ Add a missed item" is directly beneath it.
  const inventory = proposal.meal_description.trim() && (
    <p className="text-caption leading-relaxed text-subtle">
      <span className="font-mono text-micro tracking-[0.08em] text-faint">SAW </span>
      {proposal.meal_description}
    </p>
  );

  // Three things the server already worked out and nobody was told.
  //
  // `notes` is where the model records what it could not identify — "sauce could
  // not be identified" — and it was being dropped on every successful reading.
  // `is_provisional` means the server doubted the result enough not to cache it,
  // which makes going back and submitting again a real retry rather than a
  // replay; without saying so, the one person who can act on it cannot know.
  // `cached` earns its keep the other way: this reading cost nothing and is not
  // a fresh look at the plate.
  const advisories = [
    proposal.is_provisional &&
      "Trueplate isn't confident it caught everything here. Going back and submitting the photo again will take a fresh look.",
    proposal.notes,
  ].filter((line): line is string => Boolean(line));

  const advisoryNote = advisories.length > 0 && (
    // Existing tokens only. A warning surface has no colour in `@theme`, and
    // inventing one here would put a hex in a component where the design has
    // no opinion — `text-warn` already carries the signal everywhere else.
    <div className="flex flex-col gap-1 rounded-card border border-line-card bg-wash px-3.5 py-2.5">
      {advisories.map((line) => (
        <p key={line} className="text-caption leading-relaxed text-warn">
          {line}
        </p>
      ))}
    </div>
  );
  // JSX rather than a string so the count itself can be mono. Every number in
  // this app is, including the ones sitting inside a sentence — a figure that
  // reflows as it ticks over is the thing the rule exists to prevent.
  const count = (n: number) => <span className="tabular font-mono">{n}</span>;

  const roughNote =
    roughCount === 0 ? (
      "Every portion confirmed."
    ) : (
      <>
        {count(roughCount)}{" "}
        {roughCount === 1 ? "portion is a rough guess" : "portions are rough guesses"} — tap the
        grams to correct {roughCount === 1 ? "it" : "them"}.
      </>
    );

  const unresolvedNote = (
    <>
      {count(unresolved)} item{unresolved === 1 ? "" : "s"} could not be matched to a food and will
      not be saved.
    </>
  );

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

  const confidence = (draft: DraftItem) => {
    const match = draft.matched;
    // The row the numbers were read from, shown under the name the user
    // recognises. Suppressed when the two say the same thing — this line exists
    // to name a source, not to print the same words twice.
    let source: string | null = null;
    if (match && match.name.trim().toLowerCase() !== draft.name.trim().toLowerCase()) {
      source = match.brand ? `${match.brand} · ${match.name}` : match.name;
    }

    return (
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex items-center gap-2">
          <span
            className={`h-1.5 w-1.5 flex-none rounded-full ${draft.confirmed ? "bg-accent" : "bg-warn"}`}
          />
          <span className={`text-label ${draft.confirmed ? "text-accent" : "text-warn"}`}>
            {draft.matched === null
              ? "No match — edit or remove"
              : draft.confirmed
                ? "Fairly sure"
                : draft.serverLabel}
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
        {source && (
          // Truncated rather than wrapped: a USDA name runs to eight commas and
          // would push the grams input off a phone screen.
          <span className="truncate text-label text-faint" title={source}>
            {source}
          </span>
        )}
      </div>
    );
  };

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
      <div className="flex flex-none items-center gap-1.5">
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

  const footerTotals = (size: number) => (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-baseline gap-2">
        <Stat value={formatNumber(totals.calories)} size={size} />
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
          <span className="text-item font-semibold text-ink">Check before saving</span>
          <span className="tabular font-mono text-label text-faint">
            {formatDayLabel(date, true)}
          </span>
        </header>

        <main className="flex flex-1 flex-col gap-4.5 overflow-auto px-5 pt-4 pb-[150px]">
          <div className="h-[150px] flex-none">{photoPanel}</div>
          <p className="text-caption leading-relaxed text-subtle">{sourceNote}</p>
          {inventory}
          {advisoryNote}

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
                  {gramsInput(draft, "w-[118px]", "h-11.5", "text-title")}
                  <div className="flex flex-1 flex-col items-end gap-0.5">
                    <span className="tabular font-mono text-title text-ink">
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
              {unresolvedNote}
            </p>
          )}
          {error && <ErrorNote>{error}</ErrorNote>}
        </main>

        <footer className="fixed inset-x-0 bottom-0 flex flex-col gap-3 border-t border-line-2 bg-surface px-5 pt-3.5 pb-7">
          <div className="flex items-baseline justify-between">{footerTotals(26)}</div>
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
            <div className="flex-none">{inventory}</div>
            <div className="flex-none">{advisoryNote}</div>
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
                    {gramsInput(draft, "w-[104px]", "h-11", "text-entry")}

                    <div className="flex w-[118px] flex-none flex-col items-end gap-0.5">
                      <span className="tabular font-mono text-entry text-ink">
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
                  {unresolvedNote}
                </p>
              )}
              {error && <ErrorNote>{error}</ErrorNote>}
            </div>

            <div className="flex flex-none items-center justify-between gap-5 border-t border-line-2 px-8 py-4.5">
              {footerTotals(28)}
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
