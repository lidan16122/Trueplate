import type { DaySummary } from "@/types/logs";
import { dayOfMonth, dayOfWeek, shiftDays, today } from "@/utils/format";

interface Props {
  selected: string;
  /** 7 on mobile, 14 on desktop — the design uses both. */
  days: number;
  summaries: DaySummary[];
  onSelect: (iso: string) => void;
}

/** Both layouts keep week navigation beside the days so history always has a way forward. */
export function DateStrip({ selected, days, summaries, onSelect }: Props) {
  const todayISO = today();
  const hasEntries = new Map(summaries.map((s) => [s.log_date, s.has_entries]));

  // The strip ends on the selected day, so paging backwards walks history
  // rather than scrolling a fixed window.
  const dates = Array.from({ length: days }, (_, i) => shiftDays(selected, -(days - 1 - i)));

  // There is nothing to log in the future, so forward paging stops at today.
  const canGoForward = selected < todayISO;
  const nextWeek = shiftDays(selected, 7);
  const nextDate = nextWeek > todayISO ? todayISO : nextWeek;

  return (
    <div className="flex items-center gap-1.5">
      <button
        type="button"
        onClick={() => onSelect(shiftDays(selected, -7))}
        className="flex h-[66px] w-7 flex-none items-center justify-center rounded-sm bg-surface text-input text-muted transition-colors hover:bg-wash hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        aria-label="Previous week"
      >
        ‹
      </button>

      {dates.map((iso) => {
        const isSelected = iso === selected;
        const logged = hasEntries.get(iso) ?? false;

        return (
          <button
            type="button"
            key={iso}
            onClick={() => onSelect(iso)}
            aria-current={isSelected ? "date" : undefined}
            className={`flex h-[66px] min-w-0 flex-1 flex-col items-center justify-center gap-[3px] rounded-card border transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
              isSelected
                ? "border-ink bg-ink"
                : "border-line-soft bg-surface hover:border-line"
            }`}
          >
            <span
              className={`font-mono text-micro ${isSelected ? "text-on-dark-dim" : "text-faint"}`}
            >
              {dayOfWeek(iso)}
            </span>
            <span
              className={`tabular font-mono text-[17px] font-semibold ${
                isSelected ? "text-white" : "text-ink"
              }`}
            >
              {dayOfMonth(iso)}
            </span>
            {/* A dot means the day has entries — lets you find gaps at a glance. */}
            <span
              className="h-1 w-1 rounded-full"
              style={{
                background: logged
                  ? isSelected
                    ? "var(--color-accent-soft)"
                    : "var(--color-accent)"
                  : "transparent",
              }}
            />
          </button>
        );
      })}

      <button
        type="button"
        onClick={() => onSelect(nextDate)}
        disabled={!canGoForward}
        className="flex h-[66px] w-7 flex-none items-center justify-center rounded-sm bg-surface text-input text-muted transition-colors hover:bg-wash hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-default disabled:opacity-30 disabled:hover:bg-surface"
        aria-label="Next week"
      >
        ›
      </button>
    </div>
  );
}
