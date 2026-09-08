import { useAuth } from "@/hooks/useAuth";
import type { GoalType, Sex } from "@/types/profile";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import {
  INITIAL_ANSWERS,
  PAGES,
  isComplete,
  pageBlocked,
  pageIndex,
  summaryRows,
  withDrafts,
  type Drafts,
  type NumberKey,
  type PageId,
  type WizardAnswers,
} from "../models/wizardSteps";
import { useTargetPreview } from "./useTargetPreview";


/** Commits pending wizard edits before navigation so typed values survive Enter and Back. */
export function useOnboarding() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, signOut } = useAuth();

  // Returning from the reveal carries the answers back, so "change my answers"
  // is an edit rather than a restart. Names default to what Google supplied;
  // the wizard asks so they can be corrected, not so they can be typed twice.
  const resumed = (location.state as { answers?: WizardAnswers; page?: PageId } | null) ?? null;
  const [answers, setAnswers] = useState<WizardAnswers>(
    () =>
      resumed?.answers ?? {
        ...INITIAL_ANSWERS,
        firstName: user?.first_name ?? "",
        lastName: user?.last_name ?? "",
      },
  );
  const [page, setPage] = useState<PageId>(() => resumed?.page ?? "about");
  const [drafts, setDrafts] = useState<Drafts>({});

  const current = PAGES[pageIndex(page)];
  const isGoalPage = page === "goal";

  const clearDraft = useCallback((key: NumberKey) => {
    setDrafts((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  /**
   * Fold every half-typed figure in and hand the result back, rather than only
   * queueing it. Callers that commit and then act in the same tick — Enter,
   * which commits and navigates — need the committed value, not the one this
   * render closed over.
   */
  const commitAll = useCallback((): WizardAnswers => {
    const committed = withDrafts(answers, drafts);
    if (committed !== answers) setAnswers(committed);
    setDrafts({});
    return committed;
  }, [answers, drafts]);

  // Page one needs a name and a gender; page two needs a goal. Everything else
  // has a usable default, which is what lets both pages be one form. Drafts hold
  // only figures, so they cannot change this — no need to commit before asking.
  const blocked = pageBlocked(page, answers);

  const goNext = useCallback(() => {
    const committed = commitAll();
    if (blocked) return;
    if (!isGoalPage) {
      setPage("goal");
      return;
    }
    if (isComplete(committed)) navigate("/onboarding/done", { state: { answers: committed } });
  }, [commitAll, blocked, isGoalPage, navigate]);

  // Back off page one is the only way out. Until a profile exists ProtectedRoute
  // redirects every other route here — /profile, where sign-out normally lives,
  // included — so someone who picked the wrong Google account would be stuck.
  // The design draws this as a back arrow to the sign-in screen; in an app with
  // a real session that screen is only reachable by ending it, so this signs out
  // rather than navigating to a route PublicOnlyRoute would bounce straight back.
  const goBack = useCallback(async () => {
    if (isGoalPage) {
      // Commit, never discard: a typed target weight is an answer, and leaving
      // the page is not a reason to throw it away.
      commitAll();
      setPage("about");
      return;
    }
    await signOut();
    navigate("/signin", { replace: true });
  }, [isGoalPage, commitAll, signOut, navigate]);

  // The desktop footer's "Enter ↵" hint promises this, so it has to work. Arrow
  // stepping is gone with the one-figure-per-screen layout that justified it.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Enter") return;
      // A focused button turns Enter into a click of its own. Cancelling that
      // wholesale left the goal cards and Back reachable by Tab but impossible
      // to activate, which is the entire keyboard path through this page.
      if (event.target instanceof Element && event.target.closest("button, a")) return;
      event.preventDefault();
      goNext();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goNext]);

  const chooseSex = useCallback((id: Sex) => setAnswers((prev) => ({ ...prev, sex: id })), []);

  const chooseGoal = useCallback(
    (id: GoalType) => {
      // Switching goal invalidates a target weight picked for the old direction —
      // it would now be on the wrong side of current weight.
      setAnswers((prev) => ({ ...prev, goal: id, targetWeight: null }));
      clearDraft("targetWeight");
    },
    [clearDraft],
  );

  const preview = useTargetPreview(answers, isGoalPage);
  const rows = useMemo(() => summaryRows(answers), [answers]);


  return {
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
  };
}
