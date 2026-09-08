import { Navigate } from "react-router";
import { useTargetReveal } from "../hooks/useTargetReveal";

import { ErrorNote } from "@/components/ErrorNote";
import { Eyebrow } from "@/components/Eyebrow";
import { ProgressBar } from "@/components/ProgressBar";
import { Stat } from "@/components/Stat";

import { isComplete } from "../models/wizardSteps";

export function TargetReveal() {
  const { navigate, answers, targets, error, saving, start } = useTargetReveal();

  // Reached directly, or with the wizard half-finished.
  if (!answers || !isComplete(answers)) return <Navigate to="/onboarding" replace />;

  const targetCalories = targets?.target_calories ?? 0;
  const protein = targets?.protein_g ?? 0;
  const carbs = targets?.carbs_g ?? 0;
  const fat = targets?.fat_g ?? 0;

  const macros = [
    { name: "Protein", grams: protein, kcal: protein * 4 },
    { name: "Carbs", grams: carbs, kcal: carbs * 4 },
    { name: "Fat", grams: fat, kcal: fat * 9 },
  ];

  return (
    <div className="flex min-h-dvh flex-col bg-surface">
      <main className="mx-auto flex w-full max-w-[900px] flex-1 flex-col gap-10 px-7 py-12 md:px-12 md:py-16">
        <div className="flex flex-col gap-3">
          <Eyebrow>Your daily target</Eyebrow>
          <div className="flex items-baseline gap-3">
            <Stat value={targetCalories.toLocaleString()} size={64} className="md:!text-[88px]" />
            <span className="text-lead text-subtle">kcal per day</span>
          </div>
          {targets?.summary && (
            <p className="max-w-[640px] text-caption leading-relaxed text-pretty text-muted">
              {targets.summary}
            </p>
          )}
        </div>

        {/* Macro split, sized by share of total calories. */}
        <div className="flex flex-col gap-4">
          {macros.map((macro) => {
            const pct = targetCalories
              ? Math.round((macro.kcal / targetCalories) * 100)
              : 0;
            return (
              <div key={macro.name} className="flex flex-col gap-2">
                <div className="flex items-baseline justify-between">
                  <span className="text-caption text-ink">{macro.name}</span>
                  <span className="tabular font-mono text-body text-muted">
                    {macro.grams} g · {pct}%
                  </span>
                </div>
                <ProgressBar value={macro.kcal} total={targetCalories} height={6} />
              </div>
            );
          })}
        </div>

        {/* The working, shown rather than hidden. Someone told a number with no
            derivation has no reason to trust it. */}
        {targets?.math_rows && (
          <div className="flex flex-col rounded-lg border border-line">
            {targets.math_rows.map((row, i) => (
              <div
                key={row.label}
                className={`flex items-baseline justify-between gap-6 px-5 py-3.5 ${
                  i > 0 ? "border-t border-line-2" : ""
                }`}
              >
                <span className="text-caption leading-snug text-muted md:text-body">
                  {row.label}
                </span>
                <span className="tabular flex-none font-mono text-caption text-ink md:text-body">
                  {row.value}
                </span>
              </div>
            ))}
          </div>
        )}

        {error && <ErrorNote>{error}</ErrorNote>}

        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <button
            onClick={start}
            disabled={saving}
            className="h-14 rounded-lg bg-ink px-8 text-lead font-semibold text-white transition-colors hover:bg-accent disabled:opacity-50 md:h-[52px]"
          >
            {saving ? "Saving…" : "Start tracking"}
          </button>
          <button
            // Back to the goal page with the answers in hand. Passing nothing
            // sent the wizard back to its defaults, which cost one re-answer
            // when the wizard was six screens and costs every one of them now
            // that changing a goal means walking the name and body page again.
            onClick={() => navigate("/onboarding", { state: { answers, page: "goal" } })}
            className="h-14 rounded-lg border border-line px-6 text-caption text-muted transition-colors hover:border-ink hover:text-ink md:h-[52px]"
          >
            Change my answers
          </button>
        </div>
      </main>
    </div>
  );
}
