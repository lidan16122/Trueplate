import { GOAL_LABEL, GOAL_OPTIONS, type Option, SEX_LABEL, SEX_OPTIONS } from "@/lib/labels";
import type { GoalType, OnboardingPayload, Sex } from "@/types/api";

/** The four answers held as a number. */
export type NumberKey = "age" | "height" | "weight" | "targetWeight";

/**
 * One editable figure: its bounds, its step, and how it prints.
 *
 * The bounds deliberately mirror `OnboardingRequest`'s in
 * `app/schemas/onboarding.py`. Not duplication for its own sake — the server's
 * copy is what a hand-crafted request has to satisfy, and this one is what stops
 * the UI ever producing a value the server would reject.
 */
export interface NumberField {
  key: NumberKey;
  /** Also the accessible name of the input. */
  label: string;
  unit: string;
  min: number;
  max: number;
  step: number;
  decimals: number;
  hint?: string;
}

export const FIELDS: Record<NumberKey, NumberField> = {
  age: { key: "age", label: "Age", unit: "years", min: 14, max: 120, step: 1, decimals: 0 },
  height: { key: "height", label: "Height", unit: "cm", min: 50, max: 280, step: 1, decimals: 0 },
  weight: { key: "weight", label: "Weight", unit: "kg", min: 20, max: 500, step: 0.5, decimals: 1 },
  targetWeight: {
    key: "targetWeight",
    label: "Target weight",
    unit: "kg",
    min: 20,
    max: 500,
    step: 0.5,
    decimals: 1,
  },
};

/** The three figures page one asks for, in the design's order. */
export const BODY_KEYS = ["age", "height", "weight"] as const;

export interface WizardPage {
  id: "about" | "goal";
  title: string;
  sub: string;
}

/**
 * Two pages, not six questions.
 *
 * The wizard used to be a list of steps that navigation walked, which made the
 * step and the screen the same object. It is now a form per page, so a page owns
 * only its heading — what each one *contains* is laid out in `Onboarding`,
 * because the two frames arrange the same fields differently.
 */
export const PAGES: WizardPage[] = [
  {
    id: "about",
    title: "First, let’s get to know each other",
    sub: "Six answers set your starting target. All of it stays editable in your profile.",
  },
  {
    id: "goal",
    title: "What is your goal?",
    sub: "This shifts the target up or down. Nothing else about the app changes.",
  },
];

/** Segment three is the reveal screen, which is why this is one more than PAGES. */
export const TOTAL_STEPS = PAGES.length + 1;

export const SEX_CHOICES: readonly Option<Sex>[] = SEX_OPTIONS;
export const GOAL_CHOICES: readonly Option<GoalType>[] = GOAL_OPTIONS;

export interface WizardAnswers {
  firstName: string;
  lastName: string;
  age: number;
  height: number;
  weight: number;
  targetWeight: number | null;
  sex: Sex | null;
  goal: GoalType | null;
}

/** Answers the server can be sent: both choices made, and a name to save. */
export type CompletedAnswers = WizardAnswers & { sex: Sex; goal: GoalType };

export function isComplete(answers: WizardAnswers): answers is CompletedAnswers {
  // A type guard rather than `answers.sex as Sex` at the call site: the wizard
  // can be reached mid-flight via browser history, and a cast would send the
  // server a literal `null` while claiming otherwise. First name is checked here
  // too because page one gates on it, so an answer set without one never came
  // from the wizard finishing.
  return answers.sex !== null && answers.goal !== null && answers.firstName.trim() !== "";
}

export const INITIAL_ANSWERS: WizardAnswers = {
  firstName: "",
  lastName: "",
  age: 32,
  height: 172,
  weight: 74,
  targetWeight: null,
  sex: null,
  goal: null,
};

/** Maintaining has no target weight, so that row disappears entirely. */
export function showTargetWeight(goal: GoalType | null): boolean {
  return goal !== null && goal !== "maintain";
}

/**
 * Target weight is the one field whose bounds depend on an earlier answer: it
 * has to sit on the correct side of current weight, or the goal contradicts
 * itself.
 */
export function resolveField(key: NumberKey, answers: WizardAnswers): NumberField {
  const field = FIELDS[key];
  if (key !== "targetWeight") return field;

  const losing = answers.goal !== "gain";
  const weight = answers.weight;

  return {
    ...field,
    min: losing ? field.min : weight + field.step,
    max: losing ? weight - field.step : field.max,
    hint: losing ? `below ${weight.toFixed(1)} kg` : `above ${weight.toFixed(1)} kg`,
  };
}

export function fieldValue(field: NumberField, answers: WizardAnswers): number {
  // Seed a sensible default rather than making the user dial from zero.
  if (field.key === "targetWeight") return answers.targetWeight ?? defaultTargetWeight(answers);
  return answers[field.key];
}

function defaultTargetWeight(answers: WizardAnswers): number {
  return answers.weight + (answers.goal === "gain" ? 5 : -5);
}

export function clampValue(field: NumberField, value: number): number {
  const rounded = Math.round(value / field.step) * field.step;
  return Math.min(field.max, Math.max(field.min, rounded));
}

export function formatValue(field: NumberField, value: number): string {
  return field.decimals ? value.toFixed(field.decimals) : String(Math.round(value));
}

export interface SummaryRow {
  key: string;
  label: string;
  value: string;
  /** Answered rows read brighter; the rest stay dim. */
  answered: boolean;
  /** Which page the row lives on, so the sidebar can jump to it. */
  page: number;
}

/**
 * The desktop sidebar's rows. Pure, so the panel is a map over data rather than
 * seven hand-written rows that drift from what the pages actually collect.
 */
export function summaryRows(answers: WizardAnswers): SummaryRow[] {
  const name = `${answers.firstName} ${answers.lastName}`.trim();

  const rows: SummaryRow[] = [
    { key: "name", label: "Name", value: name || "—", answered: name !== "", page: 0 },
    { key: "age", label: "Age", value: `${Math.round(answers.age)} years`, answered: true, page: 0 },
    {
      key: "sex",
      label: "Gender",
      value: answers.sex ? SEX_LABEL[answers.sex] : "—",
      answered: answers.sex !== null,
      page: 0,
    },
    {
      key: "height",
      label: "Height",
      value: `${Math.round(answers.height)} cm`,
      answered: true,
      page: 0,
    },
    {
      key: "weight",
      label: "Weight",
      value: `${answers.weight.toFixed(1)} kg`,
      answered: true,
      page: 0,
    },
    {
      key: "goal",
      label: "Goal",
      value: answers.goal ? GOAL_LABEL[answers.goal] : "—",
      answered: answers.goal !== null,
      page: 1,
    },
  ];

  if (showTargetWeight(answers.goal)) {
    rows.push({
      key: "targetWeight",
      label: "Target weight",
      value: `${(answers.targetWeight ?? defaultTargetWeight(answers)).toFixed(1)} kg`,
      answered: true,
      page: 1,
    });
  }

  return rows;
}

/**
 * The one place wizard answers become a request body.
 *
 * Both callers matter: the goal page previews a target from it while the user is
 * still choosing, and the reveal screen saves with it. Built twice they could
 * differ by a default or a rounding, and the user would be shown one number and
 * held to another.
 */
export function toPayload(answers: CompletedAnswers): OnboardingPayload {
  return {
    first_name: answers.firstName.trim(),
    last_name: answers.lastName.trim(),
    age: answers.age,
    sex: answers.sex,
    height_cm: answers.height,
    weight_kg: answers.weight,
    goal_type: answers.goal,
    target_weight_kg:
      answers.goal === "maintain" ? null : (answers.targetWeight ?? defaultTargetWeight(answers)),
    rate_kg_per_week: 0.5,
    // Captured silently — daily logs are keyed on the user's local date.
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  };
}

// Re-exported so a screen that renders an answer imports its wording from the
// same module as the answer itself.
export { GOAL_LABEL, SEX_LABEL };
