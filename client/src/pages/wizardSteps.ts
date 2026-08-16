import { GOAL_OPTIONS, type Option, SEX_OPTIONS } from "@/lib/labels";
import type { GoalType, Sex } from "@/types/api";

/** Answers held as a number, and answers picked from a list. */
export type NumberKey = "age" | "height" | "weight" | "targetWeight";
export type ChoiceKey = "sex" | "goal";

interface StepBase {
  title: string;
  sub: string;
  /** Short label for the desktop answer summary. */
  summary: string;
  hint?: string;
}

export interface NumberStep extends StepBase {
  kind: "number";
  key: NumberKey;
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
  decimals?: number;
}

export interface ChoiceStep extends StepBase {
  kind: "choice";
  key: ChoiceKey;
  choices: readonly Option<Sex | GoalType>[];
}

/**
 * A discriminated union rather than one flat shape with optional fields.
 *
 * `kind` now narrows `key`, so `answers[step.key]` type-checks on its own where
 * it previously needed `step.key as "sex" | "goal"` at five separate call
 * sites — casts that would have kept compiling if a seventh step were added
 * with the wrong kind. It also makes `choices` required exactly where it is
 * used and absent where it is meaningless.
 */
export type WizardStep = NumberStep | ChoiceStep;

export interface WizardAnswers {
  age: number;
  height: number;
  weight: number;
  targetWeight: number | null;
  sex: Sex | null;
  goal: GoalType | null;
}

/** Answers with both choices made — the only shape the server can be sent. */
export type CompletedAnswers = WizardAnswers & { sex: Sex; goal: GoalType };

export function isComplete(answers: WizardAnswers): answers is CompletedAnswers {
  // A type guard rather than `answers.sex as Sex` at the call site: the wizard
  // can be reached mid-flight via browser history, and a cast would send the
  // server a literal `null` while claiming otherwise.
  return answers.sex !== null && answers.goal !== null;
}

export const INITIAL_ANSWERS: WizardAnswers = {
  age: 32,
  height: 172,
  weight: 74,
  targetWeight: null,
  sex: null,
  goal: null,
};

/** The wizard's fixed order, straight from the design. */
export const STEPS: WizardStep[] = [
  {
    key: "age",
    kind: "number",
    title: "How old are you?",
    sub: "Age changes how many calories your body burns at rest.",
    summary: "Age",
    unit: "years",
    min: 14,
    max: 120,
    step: 1,
    decimals: 0,
    hint: "14 and over",
  },
  {
    key: "sex",
    kind: "choice",
    title: "What is your gender?",
    sub: "Resting metabolism is calculated differently for male and female bodies.",
    summary: "Gender",
    choices: SEX_OPTIONS,
  },
  {
    key: "height",
    kind: "number",
    title: "How tall are you?",
    sub: "Height and weight together set the size of your body's baseline burn.",
    summary: "Height",
    unit: "cm",
    min: 50,
    max: 280,
    step: 1,
    decimals: 0,
  },
  {
    key: "weight",
    kind: "number",
    title: "What do you weigh?",
    sub: "Roughly is fine. You can update it any time, and the target follows.",
    summary: "Weight",
    unit: "kg",
    min: 20,
    max: 500,
    step: 0.5,
    decimals: 1,
  },
  {
    key: "goal",
    kind: "choice",
    title: "What are you tracking toward?",
    sub: "This only shifts the target up or down. Nothing about the app changes.",
    summary: "Goal",
    choices: GOAL_OPTIONS,
  },
  {
    key: "targetWeight",
    kind: "number",
    title: "What weight are you aiming for?",
    sub: "",
    summary: "Target weight",
    unit: "kg",
    step: 0.5,
    decimals: 1,
  },
];

/** Maintaining has no target weight, so that step disappears entirely. */
export function visibleSteps(goal: GoalType | null): WizardStep[] {
  return goal === "maintain" ? STEPS.filter((s) => s.key !== "targetWeight") : STEPS;
}

/**
 * Target weight is the one step whose bounds depend on earlier answers: it has
 * to sit on the correct side of current weight, or the goal contradicts itself.
 */
export function resolveStep(step: WizardStep, answers: WizardAnswers): WizardStep {
  if (step.kind !== "number" || step.key !== "targetWeight") return step;

  const losing = answers.goal !== "gain";
  const weight = answers.weight;

  return {
    ...step,
    title: losing ? "What weight are you aiming for?" : "What weight are you building toward?",
    sub: losing
      ? `Has to be below your current ${weight.toFixed(1)} kg. You can change it whenever.`
      : `Has to be above your current ${weight.toFixed(1)} kg. You can change it whenever.`,
    min: losing ? 20 : weight + 0.5,
    max: losing ? weight - 0.5 : 500,
    hint: losing ? `below ${weight.toFixed(1)} kg` : `above ${weight.toFixed(1)} kg`,
  };
}

export function stepValue(step: NumberStep, answers: WizardAnswers): number {
  if (step.key === "targetWeight") {
    // Seed a sensible default rather than making the user dial from zero.
    return answers.targetWeight ?? answers.weight + (answers.goal === "gain" ? 5 : -5);
  }
  return answers[step.key];
}

export function clampValue(step: NumberStep, value: number): number {
  const stepSize = step.step ?? 1;
  const rounded = Math.round(value / stepSize) * stepSize;
  return Math.min(step.max ?? Infinity, Math.max(step.min ?? -Infinity, rounded));
}

export function formatValue(step: NumberStep, value: number): string {
  return step.decimals ? value.toFixed(step.decimals) : String(Math.round(value));
}

export { GOAL_LABEL, SEX_LABEL } from "@/lib/labels";
