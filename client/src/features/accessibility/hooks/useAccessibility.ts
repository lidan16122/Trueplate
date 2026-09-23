import { useEffect, useState } from "react";

import { DEFAULT_PREFERENCES, parsePreferences } from "../models/preferences";

const STORAGE_KEY = "trueplate.accessibility.v1";

/** Preferences stay on this device and work before sign-in, including when storage is blocked. */
export function useAccessibility() {
  const [preferences, setPreferences] = useState(() => {
    try {
      return parsePreferences(localStorage.getItem(STORAGE_KEY));
    } catch {
      return { ...DEFAULT_PREFERENCES };
    }
  });
  const [canSave, setCanSave] = useState(true);

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.textSize = String(preferences.textSize);
    root.dataset.highContrast = String(preferences.highContrast);
    root.dataset.highlightLinks = String(preferences.highlightLinks);
    root.dataset.reduceMotion = String(preferences.reduceMotion);

    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences));
      setCanSave(true);
    } catch {
      // Storage restrictions must not prevent someone from using the controls.
      setCanSave(false);
    }
  }, [preferences]);

  useEffect(() => () => {
    const root = document.documentElement;
    delete root.dataset.textSize;
    delete root.dataset.highContrast;
    delete root.dataset.highlightLinks;
    delete root.dataset.reduceMotion;
  }, []);

  return { preferences, setPreferences, canSave };
}
