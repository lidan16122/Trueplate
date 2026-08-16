import type { GoalType, Sex } from "@/types/api";

/**
 * The user-facing wording for the two enum-ish answers, in one place.
 *
 * These were previously written out three times — the wizard's choice list, the
 * wizard's summary sidebar, and the profile screen — and had already drifted:
 * the sidebar said "Lose + muscle" where the other two said "Lose weight,
 * maintain muscle".
 *
 * That drift was half legitimate. A summary column has room for two words and a
 * choice card has room for a sentence, so both spellings are wanted; what was
 * wrong is that they lived apart. Each option carries `label` for the choice and
 * `short` for the summary, so adding a goal is one edit and the two can never
 * describe different sets.
 */
export interface Option<T extends string> {
  id: T;
  label: string;
  short: string;
  desc?: string;
}

export const SEX_OPTIONS: Option<Sex>[] = [
  { id: "female", label: "Female", short: "Female" },
  { id: "male", label: "Male", short: "Male" },
];

export const GOAL_OPTIONS: Option<GoalType>[] = [
  {
    id: "lose",
    label: "Lose weight, maintain muscle",
    short: "Lose + muscle",
    desc: "Lower calories & fat, high protein.",
  },
  {
    id: "maintain",
    label: "Maintain",
    short: "Maintain",
    desc: "Eat at your estimated burn.",
  },
  {
    id: "gain",
    label: "Gain weight and muscle",
    short: "Gain + muscle",
    desc: "Maximize protein and carbs.",
  },
];

function shortLabels<T extends string>(options: Option<T>[]): Record<string, string> {
  return Object.fromEntries(options.map((o) => [o.id, o.short]));
}

export const SEX_LABEL = shortLabels(SEX_OPTIONS);
export const GOAL_LABEL = shortLabels(GOAL_OPTIONS);
