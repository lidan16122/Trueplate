import { useAuth } from "@/hooks/useAuth";
import type { DayLog, DaySummary } from "@/types/logs";
import { today } from "@/utils/format";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { logsApi } from "../services/logs";


/** Keeps day loading and optimistic deletion together so failures reload the same selected date. */
export function useToday() {
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
        logsApi.day(selected),
        logsApi.range(21, selected),
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
        await logsApi.deleteEntry(entryId);
      } finally {
        void load();
      }
    },
    [load],
  );


  return { user, navigate, selected, log, summaries, error, selectDate, deleteEntry };
}
