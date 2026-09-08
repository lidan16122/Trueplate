/**
 * "Fairly sure" / "Rough guess".
 *
 * Two states rather than a percentage: a number like "0.62 confidence" is not
 * something a person can act on, but "rough guess — tap to correct" is.
 */
export function ConfidenceChip({ label, isRough }: { label: string; isRough: boolean }) {
  return (
    <span className={`text-label ${isRough ? "text-warn" : "text-accent"}`}>{label}</span>
  );
}
