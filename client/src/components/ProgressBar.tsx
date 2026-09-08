import { percentOf } from "@/utils/format";

export function ProgressBar({
  value,
  total,
  height = 6,
}: {
  value: number;
  total: number | null | undefined;
  height?: number;
}) {
  return (
    <div
      className="overflow-hidden rounded-bar bg-fill"
      style={{ height }}
      role="progressbar"
      aria-valuenow={Math.round(value)}
      aria-valuemax={total ?? undefined}
    >
      <div className="h-full bg-accent" style={{ width: percentOf(value, total) }} />
    </div>
  );
}
