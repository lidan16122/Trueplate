const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

/** `YYYY-MM-DD` in the user's own timezone, not UTC. */
export function toISODate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function today(): string {
  return toISODate(new Date());
}

/** Parse at midday so a DST shift cannot roll the date backwards. */
export function parseISODate(iso: string): Date {
  return new Date(`${iso}T12:00:00`);
}

export function shiftDays(iso: string, days: number): string {
  const date = parseISODate(iso);
  date.setDate(date.getDate() + days);
  return toISODate(date);
}

/** "Today" / "Yesterday" / "Thu, 7 August". */
export function formatDayLabel(iso: string, long = false): string {
  const todayISO = today();
  if (iso === todayISO) return "Today";
  if (iso === shiftDays(todayISO, -1)) return "Yesterday";

  const date = parseISODate(iso);
  const dow = DAY_NAMES[date.getDay()];
  return long ? `${dow}, ${date.getDate()} ${MONTHS[date.getMonth()]}` : `${dow} ${date.getDate()}`;
}

/** Always the calendar date, never "Today" — used as the secondary line. */
export function formatFullDate(iso: string): string {
  const date = parseISODate(iso);
  return `${DAY_NAMES[date.getDay()]} ${date.getDate()} ${MONTHS[date.getMonth()]}`;
}

export function dayOfWeek(iso: string): string {
  return DAY_NAMES[parseISODate(iso).getDay()];
}

export function dayOfMonth(iso: string): string {
  return String(parseISODate(iso).getDate());
}

export function formatNumber(value: number): string {
  return Math.round(value).toLocaleString();
}

export function formatGrams(value: number): string {
  return `${Math.round(value)} g`;
}

/** "31P · 28C · 4F" — the compact macro line under each entry. */
export function macroLine(protein: number, carbs: number, fat: number, spaced = false): string {
  const sep = spaced ? " " : "";
  return `${Math.round(protein)}${sep}P · ${Math.round(carbs)}${sep}C · ${Math.round(fat)}${sep}F`;
}

export function percentOf(value: number, total: number | null | undefined): string {
  if (!total) return "0%";
  return `${Math.min(100, Math.round((value / total) * 100))}%`;
}

export const MEAL_LABELS: Record<string, string> = {
  breakfast: "Breakfast",
  lunch: "Lunch",
  dinner: "Dinner",
  snack: "Snack",
};

export const MEAL_ORDER = ["breakfast", "lunch", "dinner", "snack"] as const;
