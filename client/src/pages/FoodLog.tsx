import { Link } from "react-router";

import { Eyebrow } from "@/components/ui";

/**
 * Placeholder — this screen has no design yet.
 *
 * The day view already is the food log: it has the date strip, the meal groups,
 * and history via paging. A separate screen only earns its place once there is
 * something it does better, e.g. search across all days or a week-at-a-time
 * table. Left as a route so the shape exists.
 */
export function FoodLog() {
  return (
    <div className="flex min-h-dvh flex-col bg-page">
      <main className="mx-auto flex w-full max-w-[760px] flex-1 flex-col gap-6 px-6 py-10 md:px-8">
        <Eyebrow>Food log</Eyebrow>
        <h1 className="text-[28px] font-semibold tracking-[-0.02em] text-ink">
          Not designed yet
        </h1>
        <p className="max-w-[520px] text-caption leading-relaxed text-pretty text-muted">
          Day-by-day history already lives on the today view — use the date strip to page back
          through it. This route is reserved for a search or week-table view once one is
          designed.
        </p>
        <Link
          to="/today"
          className="flex h-13 w-full items-center justify-center rounded-lg bg-ink text-lead font-semibold text-white transition-colors hover:bg-accent md:w-[200px]"
        >
          Back to today
        </Link>
      </main>
    </div>
  );
}
