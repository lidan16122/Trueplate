import { formatGrams, formatNumber, macroLine, MEAL_LABELS } from "@/lib/format";
import type { MealGroup as MealGroupData } from "@/types/api";

import { ConfidenceChip } from "./ui";

interface Props {
  group: MealGroupData;
  onDelete?: (entryId: string) => void;
}

export function MealGroup({ group, onDelete }: Props) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between">
        <h3 className="text-caption font-semibold text-ink">
          {MEAL_LABELS[group.meal_type] ?? group.meal_type}
        </h3>
        <span className="tabular font-mono text-caption text-subtle">
          {formatNumber(group.calories)} kcal
        </span>
      </div>

      <ul className="flex flex-col gap-3">
        {group.entries.map((entry) => (
          <li
            key={entry.id}
            className="group flex items-start justify-between gap-3 rounded-card border border-line bg-surface px-4 py-3"
          >
            <div className="flex min-w-0 flex-col gap-1">
              <div className="truncate text-caption text-ink">{entry.name}</div>
              <div className="flex flex-wrap items-center gap-2 text-label text-subtle">
                <span className="tabular font-mono">{formatGrams(entry.quantity_g)}</span>
                <span aria-hidden>·</span>
                <span className="tabular font-mono">
                  {macroLine(entry.protein_g, entry.carbs_g, entry.fat_g)}
                </span>
                {entry.confidence_label && (
                  <>
                    <span aria-hidden>·</span>
                    <ConfidenceChip label={entry.confidence_label} isRough={entry.is_rough} />
                  </>
                )}
              </div>
            </div>

            <div className="flex flex-none items-center gap-3">
              <span className="tabular font-mono text-caption text-ink">
                {formatNumber(entry.calories)}
              </span>
              {onDelete && (
                <button
                  onClick={() => onDelete(entry.id)}
                  aria-label={`Remove ${entry.name}`}
                  className="text-lead text-faint transition-colors hover:text-warn"
                >
                  ×
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
