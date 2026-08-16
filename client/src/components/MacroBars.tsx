import { ProgressBar } from "@/components/ui";
import type { DayLog } from "@/types/api";

/**
 * Protein / carbs / fat against target.
 *
 * Plain CSS fills, not a charting library. Three bars whose only job is
 * "how far along am I" do not need an SVG renderer, a tooltip layer, or 90 kB
 * of JavaScript — and at this size a chart library's default padding would
 * fight the layout.
 */
export function MacroBars({ log }: { log: DayLog }) {
  const rows = [
    { name: "Protein", have: log.totals.protein_g, goal: log.target_protein_g },
    { name: "Carbs", have: log.totals.carbs_g, goal: log.target_carbs_g },
    { name: "Fat", have: log.totals.fat_g, goal: log.target_fat_g },
  ];

  return (
    <div className="flex gap-2">
      {rows.map((row) => (
        <div key={row.name} className="flex flex-1 flex-col gap-1.5">
          <div className="flex items-baseline gap-[5px]">
            <span className="tabular font-mono text-caption text-ink">
              {Math.round(row.have)} g
            </span>
            {row.goal != null && (
              <span className="font-mono text-micro text-faint">of {row.goal} g</span>
            )}
          </div>
          <ProgressBar value={row.have} total={row.goal} height={3} />
          <span className="text-micro text-subtle">{row.name}</span>
        </div>
      ))}
    </div>
  );
}
