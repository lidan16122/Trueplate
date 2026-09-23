import { useOnboarding } from "../hooks/useOnboarding";
import { NameField } from "./NameField";
import { TargetPreview } from "./TargetPreview";

import { NumberStepper } from "@/components/NumberStepper";
import { GOAL_OPTIONS, SEX_OPTIONS } from "@/models/profile";

import {
  BODY_KEYS,
  FIELDS,
  TOTAL_STEPS,
  clampValue,
  fieldValue,
  formatValue,
  pageIndex,
  resolveField,
  showTargetWeight,
  withDrafts,
  type NumberKey,
} from "../models/wizardSteps";

export function Onboarding() {
  const {
    answers,
    setAnswers,
    page,
    setPage,
    drafts,
    setDrafts,
    current,
    isGoalPage,
    clearDraft,
    commitAll,
    blocked,
    goNext,
    goBack,
    chooseSex,
    chooseGoal,
    preview,
    rows,
  } = useOnboarding();

  const stepper = (key: NumberKey) => {
    const field = resolveField(key, answers);
    const value = drafts[key] ?? formatValue(field, fieldValue(field, answers));
    return (
      <NumberStepper
        value={value}
        unit={field.unit}
        label={field.label}
        onChange={(next) => setDrafts((prev) => ({ ...prev, [key]: next }))}
        onCommit={() => {
          setAnswers((prev) => withDrafts(prev, { [key]: drafts[key] }));
          clearDraft(key);
        }}
        onStep={(direction) => {
          // Steps from whatever is on screen, typed or committed. Reading the
          // render's `answers` instead would step from the pre-edit figure and
          // silently discard what the user had just typed.
          setAnswers((prev) => {
            const committed = withDrafts(prev, { [key]: drafts[key] });
            const stepped = resolveField(key, committed);
            return {
              ...committed,
              [key]: clampValue(
                stepped,
                fieldValue(stepped, committed) + direction * stepped.step,
              ),
            };
          });
          clearDraft(key);
        }}
      />
    );
  };

  return (
    <div className="flex min-h-dvh flex-col bg-surface lg:flex-row">
      {/* Desktop: live answer summary, jump back to anything already asked. */}
      <aside className="hidden w-[400px] flex-none flex-col gap-8 bg-ink p-11 lg:flex">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-sm bg-white text-item font-bold text-ink">
            T
          </div>
          <span className="text-lead font-semibold text-white">Trueplate</span>
        </div>

        <div className="flex flex-col gap-1.5">
          <div className="font-mono text-label tracking-[0.12em] text-on-dark-dim uppercase">
            Setup · {pageIndex(page) + 1} / {TOTAL_STEPS}
          </div>
          <p className="text-item leading-relaxed text-pretty text-on-dark">
            A few answers give us a starting target. It gets more accurate once you have logged a
            couple of weeks.
          </p>
        </div>

        <ul className="flex flex-col gap-0.5 border-t border-ink-3 pt-2">
          {rows.map((row) => {
            const active = row.page === page;
            return (
              <li key={row.key}>
                <button
                  onClick={() => {
                    commitAll();
                    setPage(row.page);
                  }}
                  className="-mx-2.5 flex w-[calc(100%+20px)] items-baseline justify-between gap-4 rounded-badge px-2.5 py-2.5 text-left transition-colors hover:bg-ink-2"
                >
                  <span
                    className="flex-none text-body"
                    style={{
                      color: active
                        ? "var(--color-surface)"
                        : row.answered
                          ? "var(--color-on-dark)"
                          : "var(--color-on-dark-faint)",
                    }}
                  >
                    {row.label}
                  </span>
                  <span
                    className="tabular truncate font-mono text-body"
                    style={{
                      color: active
                        ? "var(--color-accent-soft)"
                        : row.answered
                          ? "var(--color-surface)"
                          : "var(--color-on-dark-faint)",
                    }}
                  >
                    {row.value}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </aside>

      <main id="main-content" tabIndex={-1} className="flex flex-1 flex-col lg:min-w-0">
        {/* Back, segmented progress, and the step counter. */}
        <div className="flex flex-none items-center gap-3.5 px-7 pt-2 lg:h-[72px] lg:justify-between lg:border-b lg:border-line-2 lg:px-14 lg:pt-0">
          <button
            onClick={() => void goBack()}
            aria-label={isGoalPage ? "Back" : "Back to sign in"}
            className="-ml-2 flex h-[34px] w-[34px] items-center justify-center rounded-full text-entry text-muted transition-colors hover:bg-wash hover:text-ink lg:ml-0 lg:h-auto lg:w-auto lg:gap-2 lg:text-body lg:hover:bg-transparent"
          >
            <span aria-hidden>←</span>
            <span className="hidden lg:inline">Back</span>
          </button>

          <div className="flex flex-1 gap-1 lg:max-w-[280px] lg:gap-1.5">
            {Array.from({ length: TOTAL_STEPS }, (_, i) => (
              <div key={i} className="h-[3px] flex-1 overflow-hidden rounded-[2px] bg-track">
                {i <= pageIndex(page) && <div className="h-full bg-accent" />}
              </div>
            ))}
          </div>

          <span className="tabular font-mono text-label text-subtle lg:hidden">
            {pageIndex(page) + 1} / {TOTAL_STEPS}
          </span>
        </div>

        <div className="flex flex-1 flex-col px-7 pt-9 pb-8 lg:justify-center lg:overflow-auto lg:px-14 lg:py-7">
          <div className="flex max-w-[600px] flex-none flex-col gap-2.5 lg:gap-3">
            <h1 className="text-intro leading-[1.15] font-semibold tracking-[-0.025em] text-balance text-ink lg:text-hero-large lg:tracking-[-0.03em]">
              {current.title}
            </h1>
            <p className="text-item leading-relaxed text-pretty text-muted lg:text-lead">
              {current.sub}
            </p>
          </div>

          <div className="min-w-0 flex-1 pt-5.5 pb-2 lg:max-w-[660px] lg:flex-none lg:overflow-visible lg:pt-9 lg:pb-0">
            {isGoalPage ? (
              <div className="flex flex-col gap-3.5">
                <div className="flex flex-col gap-2.5">
                  {GOAL_OPTIONS.map((choice) => {
                    const selected = answers.goal === choice.id;
                    return (
                      <button
                        key={choice.id}
                        aria-pressed={selected}
                        onClick={() => chooseGoal(choice.id)}
                        className="relative flex w-full flex-col gap-1 rounded-card border border-line bg-surface px-[18px] py-4 text-left transition-colors hover:border-icon-faint"
                      >
                        <span className="flex w-full items-center justify-between gap-3">
                          <span className="text-lead font-semibold text-ink">{choice.label}</span>
                          {selected && (
                            <span className="flex h-5 w-5 flex-none items-center justify-center rounded-full bg-accent text-label text-white">
                              ✓
                            </span>
                          )}
                        </span>
                        <span className="text-caption leading-snug text-muted">{choice.desc}</span>
                        {selected && (
                          <span className="pointer-events-none absolute inset-0 rounded-card border-2 border-accent" />
                        )}
                      </button>
                    );
                  })}
                </div>

                {showTargetWeight(answers.goal) && (
                  <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-line px-4 py-3.5">
                    <div className="flex flex-col gap-0.5">
                      <span className="text-item font-medium text-ink">Target weight</span>
                      <span className="tabular font-mono text-label text-faint">
                        {resolveField("targetWeight", answers).hint}
                      </span>
                    </div>
                    {stepper("targetWeight")}
                  </div>
                )}

                <TargetPreview preview={preview} />
              </div>
            ) : (
              <div className="flex flex-col gap-[18px] lg:gap-[22px]">
                <div className="grid grid-cols-2 gap-2.5">
                  <NameField
                    label="First name"
                    placeholder="Alex"
                    value={answers.firstName}
                    onChange={(v) => setAnswers((prev) => ({ ...prev, firstName: v }))}
                  />
                  <NameField
                    label="Last name"
                    placeholder="Moreno"
                    value={answers.lastName}
                    onChange={(v) => setAnswers((prev) => ({ ...prev, lastName: v }))}
                  />
                </div>

                <div className="flex flex-col gap-[7px]">
                  <span className="text-caption text-muted">Gender</span>
                  <div className="flex gap-2">
                    {SEX_OPTIONS.map((choice) => {
                      const selected = answers.sex === choice.id;
                      return (
                        <button
                          key={choice.id}
                          aria-pressed={selected}
                          onClick={() => chooseSex(choice.id)}
                          className={`h-12 flex-1 rounded-card border text-item font-medium transition-colors ${
                            selected
                              ? "border-ink bg-ink text-white"
                              : "border-line bg-surface text-muted hover:border-ink"
                          }`}
                        >
                          {choice.label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Fields wrap and the grid drops columns so enlarged figures remain editable. */}
                <div className="flex flex-col gap-2.5 border-t border-divider pt-4 lg:grid lg:grid-cols-[repeat(auto-fit,minmax(14rem,1fr))] lg:gap-[18px]">
                  {BODY_KEYS.map((key) => (
                    <div
                      key={key}
                      className="flex flex-wrap items-center justify-between gap-3 lg:flex-col lg:items-start lg:gap-2"
                    >
                      <span className="text-item font-medium text-ink lg:text-caption lg:font-normal lg:text-muted">
                        {FIELDS[key].label}
                      </span>
                      {stepper(key)}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="flex flex-none lg:hidden">
            <button
              onClick={goNext}
              disabled={blocked}
              className="h-14 w-full rounded-lg bg-ink text-lead font-semibold text-white transition-colors hover:bg-accent disabled:opacity-35"
            >
              {isGoalPage ? "See my target" : "Continue"}
            </button>
          </div>
        </div>

        <div className="hidden h-[88px] flex-none items-center justify-end gap-5 border-t border-line-2 px-14 lg:flex">
          <span className="font-mono text-caption text-faint">Enter ↵</span>
          <button
            onClick={goNext}
            disabled={blocked}
            className="h-13 rounded-card bg-ink px-8 text-lead font-semibold text-white transition-colors hover:bg-accent disabled:opacity-35"
          >
            {isGoalPage ? "See my target" : "Continue"}
          </button>
        </div>
      </main>
    </div>
  );
}
