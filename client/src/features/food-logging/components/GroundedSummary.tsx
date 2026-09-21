import type { FoodDetectionResponse, GroundedNutritionResponse } from "@/types/detection";

const SOURCE_LABELS: Record<string, string> = {
  usda_fdc: "USDA FoodData Central",
  open_food_facts: "Open Food Facts",
  seed: "Reference record",
  manual: "Manual record",
};

/** Plain text and record citations keep the explanation tied to the reviewed meal. */
export function GroundedSummary({ summary, items }: {
  summary: GroundedNutritionResponse;
  items: FoodDetectionResponse["items"];
}) {
  const citedItems = [...new Set(summary.statements.flatMap((statement) => statement.item_indices))]
    .sort((left, right) => left - right);

  return (
    <section aria-label="Nutrition summary" className="rounded-card border border-line-card bg-wash p-3.5">
      <h3 className="mb-2 font-mono text-micro tracking-[0.08em] text-subtle">NUTRITION SUMMARY</h3>
      <ul className="flex flex-col gap-2">
        {summary.statements.map((statement) => (
          <li key={statement.fact_id} className="text-caption leading-relaxed text-muted">
            <p className="font-mono">
              {statement.text}
              {statement.item_indices.length > 0 && (
                <span className="ml-1 text-label text-faint" aria-label="Food item references">
                  [{statement.item_indices.map((index) => index + 1).join(", ")}]
                </span>
              )}
            </p>
          </li>
        ))}
      </ul>
      {citedItems.length > 0 && (
        <details className="mt-3 text-label text-subtle">
          <summary className="cursor-pointer">Nutrition sources</summary>
          <ul className="mt-2 flex flex-col gap-1 font-mono break-words">
            {citedItems.map((index) => {
              const item = items[index];
              if (!item) return null;
              const record = item.matched;
              const citation = record
                ? `${SOURCE_LABELS[record.source] ?? record.source}${record.source_ref ? ` (${record.source_ref})` : ""}`
                : "No nutrition record";
              return (
                <li key={index}>
                  [{index + 1}] {item.detected.label} · {citation}
                </li>
              );
            })}
          </ul>
        </details>
      )}
    </section>
  );
}
