import type { Targets } from "@/types/profile";
import { useEffect, useMemo, useRef, useState } from "react";
import { toPayload, type WizardAnswers } from "../models/wizardSteps";
import { onboardingApi } from "../services/onboarding";


export type PreviewState =
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
export function useTargetPreview(answers: WizardAnswers, enabled: boolean): PreviewState {
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
      onboardingApi
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
