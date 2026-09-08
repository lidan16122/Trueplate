import { useAuth } from "@/hooks/useAuth";
import type { Targets } from "@/types/profile";
import { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { isComplete, toPayload, type WizardAnswers } from "../models/wizardSteps";
import { onboardingApi } from "../services/onboarding";


/** Uses the server's preview and save results to keep the displayed target aligned with the stored goal. */
export function useTargetReveal() {
  const navigate = useNavigate();
  const { completeOnboarding } = useAuth();
  const location = useLocation();
  const answers = (location.state as { answers?: WizardAnswers } | null)?.answers;

  const [targets, setTargets] = useState<Targets | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // The number comes from the server, and only from the server. A local mirror
  // used to render first "so nothing jumps", but it was a second copy of the
  // target formula: it agreed only because the wizard collects no activity
  // level, so both ended up on the same default. Showing a placeholder for a
  // moment is a better trade than two implementations that can disagree about
  // what the user is being asked to eat.
  useEffect(() => {
    if (!answers || !isComplete(answers)) return;
    let cancelled = false;

    onboardingApi
      .preview(toPayload(answers))
      .then((result) => {
        if (!cancelled) setTargets(result);
      })
      .catch(() => {
        if (!cancelled) setError("Could not work out your target. Check your connection.");
      });

    return () => {
      cancelled = true;
    };
  }, [answers]);

  const start = useCallback(async () => {
    if (!answers || !isComplete(answers)) return;
    setSaving(true);
    setError(null);
    try {
      await onboardingApi.complete(toPayload(answers));
      // The profile and goal now exist, so lift the redirect that was holding
      // the user here — otherwise /today bounces straight back. Done locally
      // rather than by re-reading the session: the call above already proved
      // it, and a second request could only fail, which `refreshUser` would
      // read as a dead session and sign the user out on the last step.
      completeOnboarding();
      navigate("/today", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save your answers");
      setSaving(false);
    }
  }, [answers, navigate, completeOnboarding]);


  return { navigate, answers, targets, error, saving, start };
}
