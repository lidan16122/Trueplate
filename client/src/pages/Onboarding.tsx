import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router";

import { useAuth } from "@/auth/useAuth";
import { NumberStepper } from "@/components/NumberStepper";
import { api } from "@/lib/api";
import type { GoalType, Sex, Targets } from "@/types/api";

import {
  BODY_KEYS,
  clampValue,
  fieldValue,
  formatValue,
  GOAL_CHOICES,
  INITIAL_ANSWERS,
  isComplete,
  type NumberField,
  type NumberKey,
  PAGES,
  resolveField,
  SEX_CHOICES,
  showTargetWeight,
  summaryRows,
  toPayload,
  TOTAL_STEPS,
  type WizardAnswers,
} from "./wizardSteps";

/** A half-typed figure per field. Three are editable at once on page one. */
type Drafts = Partial<Record<NumberKey, string>>;

export function Onboarding() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, signOut } = useAuth();

  // Returning from the reveal carries the answers back, so "change my answers"
  // is an edit rather than a restart. Names default to what Google supplied;
  // the wizard asks so they can be corrected, not so they can be typed twice.
  const resumed = (location.state as { answers?: WizardAnswers; page?: number } | null) ?? null;
  const [answers, setAnswers] = useState<WizardAnswers>(
    () =>
      resumed?.answers ?? {
        ...INITIAL_ANSWERS,
        firstName: user?.first_name ?? "",
        lastName: user?.last_name ?? "",
      },
  );
  const [page, setPage] = useState(() => (resumed?.page === 1 ? 1 : 0));
  const [drafts, setDrafts] = useState<Drafts>({});

  const current = PAGES[page];
  const isGoalPage = current.id === "goal";

  const setNumber = useCallback((field: NumberField, next: number) => {
    setAnswers((prev) => ({ ...prev, [field.key]: clampValue(field, next) }));
  }, []);

  /** Parse and clamp whatever is half-typed, then drop the draft. */
  const commitDraft = useCallback(
    (key: NumberKey) => {
      const draft = drafts[key];
      if (draft === undefined) return;
      const parsed = Number.parseFloat(draft);
      if (!Number.isNaN(parsed)) setNumber(resolveField(key, answers), parsed);
      setDrafts((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
    },
    [drafts, answers, setNumber],
  );

  const commitAll = useCallback(() => {
    for (const key of Object.keys(drafts) as NumberKey[]) commitDraft(key);
  }, [drafts, commitDraft]);

  // Page one needs a name and a gender; page two needs a goal. Everything else
  // has a usable default, which is what lets both pages be one form.
  const blocked = isGoalPage ? answers.goal === null : !answers.firstName.trim() || !answers.sex;

  const goNext = useCallback(() => {
    commitAll();
    if (blocked) return;
    if (!isGoalPage) {
      setPage(1);
      return;
    }
    if (isComplete(answers)) navigate("/onboarding/done", { state: { answers } });
  }, [commitAll, blocked, isGoalPage, answers, navigate]);

  // Back off page one is the only way out. Until a profile exists ProtectedRoute
  // redirects every other route here — /profile, where sign-out normally lives,
  // included — so someone who picked the wrong Google account would be stuck.
  // The design draws this as a back arrow to the sign-in screen, which is what
  // signing out lands on.
  const goBack = useCallback(async () => {
    if (isGoalPage) {
      setDrafts({});
      setPage(0);
      return;
    }
    await signOut();
    navigate("/signin", { replace: true });
  }, [isGoalPage, signOut, navigate]);

  // The desktop footer's "Enter ↵" hint promises this, so it has to work. Arrow
  // stepping is gone with the one-figure-per-screen layout that justified it.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      goNext();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goNext]);

  const chooseSex = useCallback((id: Sex) => setAnswers((prev) => ({ ...prev, sex: id })), []);

  const chooseGoal = useCallback((id: GoalType) => {
    // Switching goal invalidates a target weight picked for the old direction —
    // it would now be on the wrong side of current weight.
    setAnswers((prev) => ({ ...prev, goal: id, targetWeight: null }));
    setDrafts((prev) => {
      const next = { ...prev };
      delete next.targetWeight;
      return next;
    });
  }, []);

  const preview = useTargetPreview(answers, isGoalPage);
  const rows = useMemo(() => summaryRows(answers), [answers]);

  const stepper = (key: NumberKey) => {
    const field = resolveField(key, answers);
    const value = drafts[key] ?? formatValue(field, fieldValue(field, answers));
    return (
      <NumberStepper
        value={value}
        unit={field.unit}
        label={field.label}
        onChange={(next) => setDrafts((prev) => ({ ...prev, [key]: next }))}
        onCommit={() => commitDraft(key)}
        onStep={(direction) => {
          commitDraft(key);
          setNumber(field, fieldValue(field, answers) + direction * field.step);
        }}
      />
    );
  };

  return (
    <div className="flex min-h-dvh flex-col bg-surface md:flex-row">
      {/* Desktop: live answer summary, jump back to anything already asked. */}
      <aside className="hidden w-[400px] flex-none flex-col gap-8 bg-ink p-11 md:flex">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-sm bg-white text-caption font-bold text-ink">
            T
          </div>
          <span className="text-lead font-semibold text-white">Trueplate</span>
        </div>

        <div className="flex flex-col gap-1.5">
          <div className="font-mono text-label tracking-[0.12em] text-on-dark-dim uppercase">
            Setup · {page + 1} / {TOTAL_STEPS}
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
                  onClick={() => setPage(row.page)}
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

      <main className="flex flex-1 flex-col md:min-w-0">
        {/* Back, segmented progress, and the step counter. */}
        <div className="flex flex-none items-center gap-3.5 px-7 pt-2 md:h-[72px] md:justify-between md:border-b md:border-line-2 md:px-14 md:pt-0">
          <button
            onClick={() => void goBack()}
            aria-label={isGoalPage ? "Back" : "Back to sign in"}
            className="-ml-2 flex h-[34px] w-[34px] items-center justify-center rounded-full text-[17px] text-muted transition-colors hover:bg-wash hover:text-ink md:ml-0 md:h-auto md:w-auto md:gap-2 md:text-body md:hover:bg-transparent"
          >
            <span aria-hidden>←</span>
            <span className="hidden md:inline">Back</span>
          </button>

          <div className="flex flex-1 gap-1 md:w-[280px] md:flex-none md:gap-1.5">
            {Array.from({ length: TOTAL_STEPS }, (_, i) => (
              <div key={i} className="h-[3px] flex-1 overflow-hidden rounded-[2px] bg-track">
                {i <= page && <div className="h-full bg-accent" />}
              </div>
            ))}
          </div>

          <span className="tabular font-mono text-label text-subtle md:hidden">
            {page + 1} / {TOTAL_STEPS}
          </span>
        </div>

        <div className="flex flex-1 flex-col px-7 pt-9 pb-8 md:justify-center md:overflow-auto md:px-14 md:py-7">
          <div className="flex max-w-[600px] flex-none flex-col gap-2.5 md:gap-3">
            <h1 className="text-[30px] leading-[1.15] font-semibold tracking-[-0.025em] text-balance text-ink md:text-[40px] md:tracking-[-0.03em]">
              {current.title}
            </h1>
            <p className="text-item leading-relaxed text-pretty text-muted md:text-lead">
              {current.sub}
            </p>
          </div>

          <div className="flex-1 overflow-auto pt-5.5 pb-2 md:max-w-[660px] md:flex-none md:overflow-visible md:pt-9 md:pb-0">
            {isGoalPage ? (
              <div className="flex flex-col gap-3.5">
                <div className="flex flex-col gap-2.5">
                  {GOAL_CHOICES.map((choice) => {
                    const selected = answers.goal === choice.id;
                    return (
                      <button
                        key={choice.id}
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
                  <div className="flex items-center justify-between gap-3 rounded-card border border-line px-4 py-3.5">
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
              <div className="flex flex-col gap-[18px] md:gap-[22px]">
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
                    {SEX_CHOICES.map((choice) => {
                      const selected = answers.sex === choice.id;
                      return (
                        <button
                          key={choice.id}
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

                {/* Mobile lays these out as rows, desktop as three columns. */}
                <div className="flex flex-col gap-2.5 border-t border-divider pt-4 md:grid md:grid-cols-3 md:gap-[18px]">
                  {BODY_KEYS.map((key) => (
                    <div
                      key={key}
                      className="flex items-center justify-between gap-3 md:flex-col md:items-start md:gap-2"
                    >
                      <span className="text-item font-medium text-ink md:text-caption md:font-normal md:text-muted">
                        {FIELD_LABEL[key]}
                      </span>
                      {stepper(key)}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="flex flex-none md:hidden">
            <button
              onClick={goNext}
              disabled={blocked}
              className="h-14 w-full rounded-lg bg-ink text-lead font-semibold text-white transition-colors hover:bg-accent disabled:opacity-35"
            >
              {isGoalPage ? "See my target" : "Continue"}
            </button>
          </div>
        </div>

        <div className="hidden h-[88px] flex-none items-center justify-end gap-5 border-t border-line-2 px-14 md:flex">
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

const FIELD_LABEL: Record<(typeof BODY_KEYS)[number], string> = {
  age: "Age",
  height: "Height",
  weight: "Weight",
};

function NameField({
  label,
  placeholder,
  value,
  onChange,
}: {
  label: string;
  placeholder: string;
  value: string;
  onChange: (next: string) => void;
}) {
  return (
    <label className="flex min-w-0 flex-col gap-[7px]">
      <span className="text-caption text-muted">{label}</span>
      <input
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="h-[50px] w-full min-w-0 rounded-card border border-line bg-surface px-3.5 text-lead text-ink outline-none focus:border-accent"
      />
    </label>
  );
}

/** The dark card on the goal page: the target as it stands, before it is saved. */
function TargetPreview({ preview }: { preview: PreviewState }) {
  // "Working it out…" is only true while a request is actually outstanding. Left
  // as the catch-all it reads as progress on a request that has already failed,
  // which is the one case where the user is owed a different sentence.
  const note = {
    idle: "Answer the basics and your target appears here.",
    loading: "Working it out…",
    error: "Could not reach the server. The reveal will try again.",
    ready: "",
  }[preview.status];

  return (
    <div className="flex items-baseline justify-between gap-3.5 rounded-lg bg-ink px-5 py-[18px]">
      <div className="flex flex-col gap-1.5">
        <span className="font-mono text-label tracking-[0.12em] text-on-dark-dim uppercase">
          Daily target
        </span>
        <span className="text-caption leading-snug text-on-dark">
          {preview.status === "ready"
            ? `${preview.targets.protein_g} g protein · ${preview.targets.carbs_g} g carbs · ${preview.targets.fat_g} g fat`
            : note}
        </span>
      </div>
      <div className="flex flex-none items-baseline gap-1.5">
        <span className="tabular font-mono text-figure font-medium tracking-[-0.03em] text-white">
          {preview.status === "ready" ? preview.targets.target_calories.toLocaleString() : "—"}
        </span>
        <span className="text-caption text-on-dark-dim">kcal</span>
      </div>
    </div>
  );
}

type PreviewState =
  /** Not enough answers to ask — reachable by jumping here from the sidebar. */
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; targets: Targets };

/**
 * The live target, from the server and only from the server.
 *
 * `TargetReveal` had a local mirror of this formula once and it was removed:
 * two implementations can disagree about what the user is being asked to eat,
 * and the one on screen is the one they act on. Computing it here instead would
 * put that mirror back one step earlier in the flow.
 *
 * The goal is defaulted to `maintain` before a card is tapped so the card opens
 * with the user's estimated burn rather than a dash — that is the number the
 * design shows there, and it is a true answer to "what if I changed nothing".
 */
function useTargetPreview(answers: WizardAnswers, enabled: boolean): PreviewState {
  const [state, setState] = useState<PreviewState>({ status: "idle" });
  // Ignore a slow reply that lands after a newer one: the user is tapping goal
  // cards, and an out-of-order response would show a target for the goal they
  // just moved away from.
  const latest = useRef(0);

  // No sex, no preview. The sidebar can jump straight to the goal page without
  // one, and a defaulted sex would show a confidently wrong number rather than
  // no number.
  const payload = useMemo(
    () =>
      enabled && answers.sex !== null
        ? toPayload({ ...answers, sex: answers.sex, goal: answers.goal ?? "maintain" })
        : null,
    [answers, enabled],
  );

  useEffect(() => {
    if (payload === null) {
      setState({ status: "idle" });
      return;
    }
    const request = ++latest.current;
    // Debounced: a held-down stepper button would otherwise fire a request per
    // repeat, and only the last one's answer is ever shown.
    const timer = setTimeout(() => {
      // Keep the last good number on screen while a newer one is in flight —
      // flashing back to "—" between two valid targets reads as breakage.
      setState((prev) => (prev.status === "ready" ? prev : { status: "loading" }));
      api.onboarding
        .preview(payload)
        .then((targets) => {
          if (request === latest.current) setState({ status: "ready", targets });
        })
        .catch(() => {
          if (request === latest.current) setState({ status: "error" });
        });
    }, 250);

    return () => clearTimeout(timer);
  }, [payload]);

  return state;
}
