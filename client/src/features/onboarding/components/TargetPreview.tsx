import type { PreviewState } from "../hooks/useTargetPreview";


/** The dark card on the goal page: the target as it stands, before it is saved. */
export function TargetPreview({ preview }: { preview: PreviewState }) {
  // "Working it out…" is only true while a request is actually outstanding. Left
  // as the catch-all it reads as progress on a request that has already failed,
  // which is the one case where the user is owed a different sentence.
  const note = {
    idle: "Answer the basics and your target appears here.",
    loading: "Working it out…",
    error: "Could not reach the server. The reveal will try again.",
    ready: "",
  }[preview.status];

  return (
    <div className="flex items-baseline justify-between gap-3.5 rounded-lg bg-ink px-5 py-[18px]">
      <div className="flex flex-col gap-1.5">
        <span className="font-mono text-label tracking-[0.12em] text-on-dark-dim uppercase">
          Daily target
        </span>
        {/* Mono only on the branch that carries figures — the fallback is prose,
            and the three grams move as goals are tapped, which is exactly the
            reflow `tabular` exists to stop. */}
        {preview.status === "ready" ? (
          <span className="tabular font-mono text-caption leading-snug text-on-dark">
            {preview.targets.protein_g} g protein · {preview.targets.carbs_g} g carbs ·{" "}
            {preview.targets.fat_g} g fat
          </span>
        ) : (
          <span className="text-caption leading-snug text-on-dark">{note}</span>
        )}
      </div>
      <div className="flex flex-none items-baseline gap-1.5">
        <span className="tabular font-mono text-figure font-medium tracking-[-0.03em] text-white">
          {preview.status === "ready" ? preview.targets.target_calories.toLocaleString() : "—"}
        </span>
        <span className="text-caption text-on-dark-dim">kcal</span>
      </div>
    </div>
  );
}
