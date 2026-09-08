import type { DayLog, DaySummary, FoodEntryCreate } from "@/types/logs";

import { del, get, patch, post } from "@/services/http";

export const logsApi = {
    day: (date: string) => get<DayLog>(`/logs/${date}`),
    range: (days: number, end?: string) =>
      get<DaySummary[]>(`/logs?days=${days}${end ? `&end=${end}` : ""}`),
    addEntries: (date: string, entries: FoodEntryCreate[]) =>
      post<DayLog>(`/logs/${date}/entries`, { entries }),
    updateEntry: (entryId: string, quantityG: number) =>
      patch<unknown>(`/logs/entries/${entryId}`, { quantity_g: quantityG }),
    deleteEntry: (entryId: string) => del<void>(`/logs/entries/${entryId}`),
  };
