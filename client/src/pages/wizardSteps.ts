import type { GoalType, Sex } from "@/types/api";

export interface Choice {
  id: string;
  label: string;
  desc?: string;
}

export interface WizardStep {
  key: "age" | "sex" | "height" | "weight" | "goal" | "targetWeight";
  kind: "number" | "choice";
  title: string;
  sub: string;
  /** Short label for the desktop answer summary. */
  summary: string;
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
  decimals?: number;
  hint?: string;
  choices?: Choice[];
}

export interface WizardAnswers {
  age: number;
  height: number;
  weight: number;
  targetWeight: number | null;
  sex: Sex | null;
  goal: GoalType | null;
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
    choices: [
      { id: "female", label: "Female" },
      { id: "male", label: "Male" },
    ],
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
    choices: [
      { id: "lose", label: "Lose weight, maintain muscle", desc: "Lower calories & fat, high protein." },
      { id: "maintain", label: "Maintain", desc: "Eat at your estimated burn." },
      { id: "gain", label: "Gain weight and muscle", desc: "Maximize protein and carbs." },
    ],
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
  if (step.key !== "targetWeight") return step;

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

export function stepValue(step: WizardStep, answers: WizardAnswers): number {
  if (step.key === "targetWeight") {
    // Seed a sensible default rather than making the user dial from zero.
    return answers.targetWeight ?? answers.weight + (answers.goal === "gain" ? 5 : -5);
  }
  return answers[step.key as "age" | "height" | "weight"];
}

export function clampValue(step: WizardStep, value: number): number {
  const stepSize = step.step ?? 1;
  const rounded = Math.round(value / stepSize) * stepSize;
  return Math.min(step.max ?? Infinity, Math.max(step.min ?? -Infinity, rounded));
}

export function formatValue(step: WizardStep, value: number): string {
  return step.decimals ? value.toFixed(step.decimals) : String(Math.round(value));
}

export const SEX_LABEL: Record<string, string> = { female: "Female", male: "Male" };
export const GOAL_LABEL: Record<string, string> = {
  lose: "Lose + muscle",
  maintain: "Maintain",
  gain: "Gain + muscle",
};
