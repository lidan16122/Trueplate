export const TEXT_SIZES = [100, 125, 150] as const;

export interface AccessibilityPreferences {
  textSize: (typeof TEXT_SIZES)[number];
  highContrast: boolean;
  highlightLinks: boolean;
  reduceMotion: boolean;
}

export const DEFAULT_PREFERENCES: AccessibilityPreferences = {
  textSize: 100,
  highContrast: false,
  highlightLinks: false,
  reduceMotion: false,
};

// Browser storage can be edited or left behind by an older version of the app.
// Only supported values may change the page's presentation.
export function parsePreferences(stored: string | null): AccessibilityPreferences {
  try {
    const value: unknown = JSON.parse(stored ?? "null");
    if (!value || typeof value !== "object") return { ...DEFAULT_PREFERENCES };

    const record = value as Record<string, unknown>;
    return {
      textSize: record.textSize === 125 || record.textSize === 150 ? record.textSize : 100,
      highContrast: record.highContrast === true,
      highlightLinks: record.highlightLinks === true,
      reduceMotion: record.reduceMotion === true,
    };
  } catch {
    return { ...DEFAULT_PREFERENCES };
  }
}
