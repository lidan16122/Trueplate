/**
 * Scaling a per-100 g figure to an actual portion.
 *
 * This is display arithmetic over numbers the server already resolved, not a
 * second implementation of anything: the entry stores per-100 g values and a
 * gram quantity, so editing the portion recomputes locally without a round
 * trip, and what gets saved is still the per-100 g pair.
 *
 * Deliberately the *only* nutrition maths on the client. Targets — BMR, TDEE,
 * the macro split — come from the server, because the inputs they derive from
 * live there and a second copy of that formula drifts.
 */
export function scaleTo(grams: number, per100g: number): number {
  return (per100g * grams) / 100;
}
