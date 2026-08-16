import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { useAuth } from "@/auth/useAuth";
import { DateStrip } from "@/components/DateStrip";
import { MacroBars } from "@/components/MacroBars";
import { MealGroup } from "@/components/MealGroup";
import { Avatar, EmptyState, ErrorNote, ProgressBar, Stat } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDayLabel, formatFullDate, formatNumber, shiftDays, today } from "@/lib/format";
import type { DayLog, DaySummary } from "@/types/api";

export function Today() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();

  const selected = params.get("date") ?? today();
  const [log, setLog] = useState<DayLog | null>(null);
  const [summaries, setSummaries] = useState<DaySummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [dayLog, range] = await Promise.all([
        api.logs.day(selected),
        api.logs.range(21, selected),
      ]);
      setLog(dayLog);
      setSummaries(range);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load this day");
    }
  }, [selected]);

  useEffect(() => {
    void load();
  }, [load]);

  const selectDate = useCallback(
    (iso: string) => {
      setParams(iso === today() ? {} : { date: iso });
    },
    [setParams],
  );

  const deleteEntry = useCallback(
    async (entryId: string) => {
      // Optimistic: the row disappears immediately, and a failure reloads the
      // real state rather than leaving a phantom deletion on screen.
      setLog((prev) =>
        prev
          ? {
              ...prev,
              groups: prev.groups
                .map((g) => ({ ...g, entries: g.entries.filter((e) => e.id !== entryId) }))
                .filter((g) => g.entries.length > 0),
            }
          : prev,
      );
      try {
        await api.logs.deleteEntry(entryId);
      } finally {
        void load();
      }
    },
    [load],
  );

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
