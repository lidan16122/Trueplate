import { Link } from "react-router";
import { useToday } from "../hooks/useToday";

import { Avatar } from "@/components/Avatar";
import { EmptyState } from "@/components/EmptyState";
import { ErrorNote } from "@/components/ErrorNote";
import { ProgressBar } from "@/components/ProgressBar";
import { Stat } from "@/components/Stat";
import { formatDayLabel, formatFullDate, formatNumber, shiftDays } from "@/utils/format";
import { DateStrip } from "./DateStrip";
import { MacroBars } from "./MacroBars";
import { MealGroup } from "./MealGroup";

export function Today() {
  const { user, navigate, selected, log, summaries, error, selectDate, deleteEntry } = useToday();

  const eaten = log?.totals.calories ?? 0;
  const target = log?.target_calories ?? null;
  const remaining = target != null ? target - eaten : null;
  const hasEntries = (log?.groups.length ?? 0) > 0;

  return (
    <div className="min-h-dvh bg-page">
      {/* Desktop chrome */}
      <header className="hidden h-16 items-center justify-between border-b border-line-2 bg-surface px-8 md:flex">
        <Link to="/today" className="flex items-center gap-3">
          <span className="flex h-7 w-7 items-center justify-center rounded-badge bg-ink text-caption font-bold text-white">
            T
          </span>
          <span className="text-caption font-semibold text-ink">Trueplate</span>
        </Link>
        <div className="flex items-center gap-3.5">
          <button
            onClick={() => navigate("/add")}
            className="h-10 rounded-md bg-ink px-5 text-body font-semibold text-white transition-colors hover:bg-accent"
          >
            Add food
          </button>
          <Avatar initials={user?.initials ?? "?"} />
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1100px] px-6 pt-4 pb-32 md:px-8 md:pt-6 md:pb-12">
        {/* Mobile chrome */}
        <div className="flex items-center justify-between md:hidden">
          <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-ink">
            {formatDayLabel(selected, true)}
          </h1>
          <Avatar initials={user?.initials ?? "?"} />
        </div>

        <div className="mt-4 md:hidden">
          <DateStrip
            selected={selected}
            days={7}
            summaries={summaries}
            onSelect={selectDate}
            onShiftWeek={(dir) => selectDate(shiftDays(selected, dir * 7))}
            showPaging
          />
        </div>

        <div className="hidden md:block">
          <DateStrip selected={selected} days={14} summaries={summaries} onSelect={selectDate} />
        </div>

        <div className="mt-6 hidden items-baseline justify-between md:flex">
          <h1 className="text-[24px] font-semibold tracking-[-0.02em] text-ink">
            {formatDayLabel(selected, true)}
          </h1>
          <span className="font-mono text-caption text-faint">{formatFullDate(selected)}</span>
        </div>

        {error && (
          <div className="mt-6">
            <ErrorNote>{error}</ErrorNote>
          </div>
        )}

        {log && (
          <>
            {/* Totals */}
            <section className="mt-6 flex flex-col gap-3.5">
              <div className="flex items-end justify-between">
                <div className="flex items-baseline gap-2">
                  <Stat value={formatNumber(eaten)} size={44} />
                  <span className="font-mono text-body text-subtle">
                    {target != null ? `of ${target.toLocaleString()} kcal` : "kcal"}
                  </span>
                </div>
                {remaining != null && (
                  <div className="text-right">
                    <div className="tabular font-mono text-[17px] text-ink">
                      {formatNumber(Math.abs(remaining))}
                    </div>
                    <div className="text-label text-subtle">
                      {remaining >= 0 ? "left today" : "over target"}
                    </div>
                  </div>
                )}
              </div>

              <ProgressBar value={eaten} total={target} />
              <MacroBars log={log} />
            </section>

            {/* Entries */}
            <section className="mt-8 flex flex-col gap-6">
              {hasEntries ? (
                log.groups.map((group) => (
                  <MealGroup key={group.meal_type} group={group} onDelete={deleteEntry} />
                ))
              ) : (
                <EmptyState
                  title={`Nothing logged on ${formatFullDate(selected)}`}
                  body="Photograph a meal to fill this day in."
                />
              )}
            </section>
          </>
        )}
      </main>

      {/* Mobile primary action — pinned, not a tab bar. The design has no tabs. */}
      <div className="fixed inset-x-0 bottom-0 px-6 pt-4 pb-8 md:hidden">
        <button
          onClick={() => navigate("/add")}
          className="flex h-15 w-full items-center justify-center gap-2.5 rounded-xl bg-ink text-lead font-semibold text-white shadow-[0_12px_28px_-12px_rgba(20,22,26,0.5)] transition-colors hover:bg-accent"
        >
          <span className="flex h-5 w-5 items-center justify-center rounded-chip border-[1.5px] border-white">
            <span className="h-[7px] w-[7px] rounded-full border-[1.5px] border-white" />
          </span>
          Add food
        </button>
      </div>
    </div>
  );
}
