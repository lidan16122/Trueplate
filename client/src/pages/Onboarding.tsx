import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";


import {
  clampValue,
  formatValue,
  GOAL_LABEL,
  INITIAL_ANSWERS,
  resolveStep,
  SEX_LABEL,
  stepValue,
  visibleSteps,
  type WizardAnswers,
} from "./wizardSteps";

export function Onboarding() {
  const navigate = useNavigate();
  const [answers, setAnswers] = useState<WizardAnswers>(INITIAL_ANSWERS);
  const [index, setIndex] = useState(0);
  const [draft, setDraft] = useState<string | null>(null);

  const steps = useMemo(() => visibleSteps(answers.goal), [answers.goal]);
  const step = resolveStep(steps[Math.min(index, steps.length - 1)], answers);
  const value = stepValue(step, answers);
  const isNumber = step.kind === "number";

  const setNumber = useCallback(
    (next: number) => {
      const clamped = clampValue(step, next);
      setAnswers((prev) => ({ ...prev, [step.key]: clamped }));
    },
    [step],
  );

  const commitDraft = useCallback(() => {
    if (draft === null) return;
    const parsed = Number.parseFloat(draft);
    if (!Number.isNaN(parsed)) setNumber(parsed);
    setDraft(null);
  }, [draft, setNumber]);

  const goNext = useCallback(() => {
    commitDraft();
    if (step.kind === "choice" && !answers[step.key as "sex" | "goal"]) return;

    if (index >= steps.length - 1) {
      navigate("/onboarding/done", { state: { answers } });
      return;
    }
    setIndex((i) => i + 1);
  }, [commitDraft, step, answers, index, steps.length, navigate]);

  const goBack = useCallback(() => {
    if (index === 0) return;
    setDraft(null);
    setIndex((i) => i - 1);
  }, [index]);

  // Keyboard: Enter advances, arrows step the value. The design's desktop hint
  // ("↑ ↓ to step") promises this, so it has to actually work.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Enter") {
        event.preventDefault();
        goNext();
      } else if (isNumber && (event.key === "ArrowUp" || event.key === "ArrowDown")) {
        event.preventDefault();
        setDraft(null);
        setNumber(value + (event.key === "ArrowUp" ? 1 : -1) * (step.step ?? 1));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goNext, isNumber, setNumber, value, step.step]);

  const chooseOption = useCallback(
    (id: string) => {
      setAnswers((prev) => {
        const next = { ...prev, [step.key]: id } as WizardAnswers;
        // Switching goal invalidates a target weight picked for the old
        // direction — it would now be on the wrong side of current weight.
        if (step.key === "goal") next.targetWeight = null;
        return next;
      });
      // Brief pause so the selection is visibly registered before moving on.
      setTimeout(() => setIndex((i) => Math.min(i + 1, steps.length - 1)), 140);
    },
    [step.key, steps.length],
  );

  // The final step hands off to the reveal screen, which shows the target and
  // is where the answers are actually saved.
  const isLastStep = index >= steps.length - 1;
  const blocked = step.kind === "choice" && !answers[step.key as "sex" | "goal"];
  const displayValue = draft ?? formatValue(step, value);

  const summaryRows = steps.map((s, i) => {
    const answered = s.kind === "number" ? i <= index : Boolean(answers[s.key as "sex" | "goal"]);
    let shown = "—";
    if (answered) {
      if (s.key === "sex") shown = SEX_LABEL[answers.sex ?? ""] ?? "—";
      else if (s.key === "goal") shown = GOAL_LABEL[answers.goal ?? ""] ?? "—";
      else {
        const resolved = resolveStep(s, answers);
        shown = `${formatValue(resolved, stepValue(resolved, answers))} ${resolved.unit ?? ""}`.trim();
      }
    }
    return { step: s, index: i, label: s.summary, value: shown, answered, active: i === index };
  });

  return (
    <div className="flex min-h-dvh flex-col bg-surface md:flex-row">
      {/* Desktop: live answer summary, jump back to anything answered. */}
      <aside className="hidden w-[400px] flex-none flex-col gap-8 bg-ink p-11 md:flex">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-sm bg-white text-caption font-bold text-ink">
            T
          </div>
          <span className="text-lead font-semibold text-white">Trueplate</span>
        </div>

        <div className="font-mono text-label tracking-[0.12em] text-on-dark-dim uppercase">
          Setup · {index + 1} / {steps.length}
        </div>

        <ul className="flex flex-col gap-3">
          {summaryRows.map((row) => (
            <li key={row.step.key}>
              <button
                onClick={() => (row.answered || row.index <= index) && setIndex(row.index)}
                disabled={!row.answered && row.index > index}
                className="flex w-full items-baseline justify-between gap-4 text-left disabled:cursor-default"
              >
                <span
                  className="text-body"
                  style={{
                    color: row.active ? "var(--color-surface)" : row.answered ? "var(--color-on-dark)" : "var(--color-on-dark-faint)",
                  }}
                >
                  {row.label}
                </span>
                <span
                  className="tabular font-mono text-body"
                  style={{
                    color: row.active ? "var(--color-accent-soft)" : row.answered ? "var(--color-surface)" : "var(--color-on-dark-faint)",
                  }}
                >
                  {row.value}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      {/* Question pane */}
      <main className="flex flex-1 flex-col px-7 pt-8 pb-10 md:px-16 md:py-14">
        {/* Segmented progress */}
        <div className="flex items-center gap-3">
          <div className="flex flex-1 gap-1.5">
            {steps.map((s, i) => (
              <div key={s.key} className="h-[3px] flex-1 overflow-hidden rounded-[2px] bg-fill">
                {i <= index && <div className="h-full bg-accent" />}
              </div>
            ))}
          </div>
          <span className="font-mono text-label text-subtle md:hidden">
            {index + 1} / {steps.length}
          </span>
        </div>

        <div className="flex flex-1 flex-col justify-center gap-8 py-10">
          <div className="flex flex-col gap-2.5">
            <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.02em] text-balance text-ink md:text-[38px]">
              {step.title}
            </h1>
            {step.sub && (
              <p className="max-w-[520px] text-caption leading-relaxed text-pretty text-muted md:text-lead">
                {step.sub}
              </p>
            )}
          </div>

          {isNumber ? (
            <div className="flex flex-col gap-4">
              <div className="flex items-center gap-4">
                <input
                  inputMode="decimal"
                  value={displayValue}
                  onChange={(e) => setDraft(e.target.value)}
                  onBlur={commitDraft}
                  aria-label={step.summary}
                  className="tabular w-[190px] border-b border-line bg-transparent pb-2 font-mono text-[64px] leading-none font-medium tracking-[-0.04em] text-ink outline-none focus:border-accent md:text-[88px]"
                />
                <span className="text-lead text-subtle">{step.unit}</span>

                <div className="ml-auto flex gap-2">
                  <button
                    onClick={() => {
                      setDraft(null);
                      setNumber(value - (step.step ?? 1));
                    }}
                    className="flex h-11 w-11 items-center justify-center rounded-card border border-line text-[18px] text-ink transition-colors hover:bg-wash"
                    aria-label="Decrease"
                  >
                    −
                  </button>
                  <button
                    onClick={() => {
                      setDraft(null);
                      setNumber(value + (step.step ?? 1));
                    }}
                    className="flex h-11 w-11 items-center justify-center rounded-card border border-line text-[18px] text-ink transition-colors hover:bg-wash"
                    aria-label="Increase"
                  >
                    +
                  </button>
                </div>
              </div>
              <p className="font-mono text-caption text-faint">
                ↑ ↓ to step{step.hint ? ` · ${step.hint}` : ""}
              </p>
            </div>
          ) : (
            <div className="flex max-w-[560px] flex-col gap-2.5">
              {step.choices?.map((choice) => {
                const selected = answers[step.key as "sex" | "goal"] === choice.id;
                return (
                  <button
                    key={choice.id}
                    onClick={() => chooseOption(choice.id)}
                    className={`flex items-center justify-between gap-4 rounded-lg border px-5 py-4 text-left transition-colors ${
                      selected ? "border-ink bg-ink" : "border-line bg-surface hover:border-ink"
                    }`}
                  >
                    <span className="flex flex-col gap-1">
                      <span
                        className={`text-lead font-semibold ${selected ? "text-white" : "text-ink"}`}
                      >
                        {choice.label}
                      </span>
                      {choice.desc && (
                        <span
                          className={`text-caption ${selected ? "text-on-dark" : "text-subtle"}`}
                        >
                          {choice.desc}
                        </span>
                      )}
                    </span>
                    {selected && <span className="text-lead text-accent-soft">✓</span>}
                  </button>
                );
              })}
            </div>
          )}

        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={goBack}
            disabled={index === 0}
            className="h-13 rounded-lg border border-line px-6 text-caption text-muted transition-colors hover:border-ink hover:text-ink disabled:opacity-30"
          >
            Back
          </button>
          <button
            onClick={goNext}
            disabled={blocked}
            className="h-13 flex-1 rounded-lg bg-ink text-lead font-semibold text-white transition-colors hover:bg-accent disabled:opacity-35 md:flex-none md:px-10"
          >
            {isLastStep ? "See my target" : "Continue"}
          </button>
        </div>
      </main>
    </div>
  );
}
