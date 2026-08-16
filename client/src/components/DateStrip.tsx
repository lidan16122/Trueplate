import { dayOfMonth, dayOfWeek, shiftDays, today } from "@/lib/format";
import type { DaySummary } from "@/types/api";

interface Props {
  selected: string;
  /** 7 on mobile, 14 on desktop — the design uses both. */
  days: number;
  summaries: DaySummary[];
  onSelect: (iso: string) => void;
  onShiftWeek?: (direction: -1 | 1) => void;
  showPaging?: boolean;
}

export function DateStrip({
  selected,
  days,
  summaries,
  onSelect,
  onShiftWeek,
  showPaging = false,
}: Props) {
  const todayISO = today();
  const hasEntries = new Map(summaries.map((s) => [s.log_date, s.has_entries]));

  // The strip ends on the selected day, so paging backwards walks history
  // rather than scrolling a fixed window.
  const dates = Array.from({ length: days }, (_, i) => shiftDays(selected, -(days - 1 - i)));

  // There is nothing to log in the future, so forward paging stops at today.
  const canGoForward = selected < todayISO;

  return (
    <div className="flex items-center gap-1.5">
      {showPaging && (
        <button
          onClick={() => onShiftWeek?.(-1)}
          className="flex h-[66px] w-7 flex-none items-center justify-center rounded-sm text-lead text-faint transition-colors hover:bg-wash hover:text-ink"
          aria-label="Previous week"
        >
          ‹
        </button>
      )}

      {dates.map((iso) => {
        const isSelected = iso === selected;
        const logged = hasEntries.get(iso) ?? false;

        return (
          <button
            key={iso}
            onClick={() => onSelect(iso)}
            aria-current={isSelected ? "date" : undefined}
            className={`flex h-[66px] min-w-0 flex-1 flex-col items-center justify-center gap-[3px] rounded-card border transition-colors ${
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

      {showPaging && (
        <button
          onClick={() => onShiftWeek?.(1)}
          disabled={!canGoForward}
          className="flex h-[66px] w-7 flex-none items-center justify-center rounded-sm text-lead text-faint transition-colors hover:bg-wash hover:text-ink disabled:opacity-30 disabled:hover:bg-transparent"
          aria-label="Next week"
        >
          ›
        </button>
      )}
    </div>
  );
}
