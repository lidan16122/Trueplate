import { useEffect, useId, useRef, useState } from "react";

import { useAccessibility } from "../hooks/useAccessibility";
import { DEFAULT_PREFERENCES, TEXT_SIZES } from "../models/preferences";

/** A native modal keeps focus inside the preferences while the page behind it is inert. */
export function AccessibilityMenu() {
  const { preferences, setPreferences, canSave } = useAccessibility();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previousOverflow; };
  }, [open]);

  return (
    <>
      <button
        ref={launcherRef}
        type="button"
        className="accessibility-launcher"
        aria-label="Accessibility settings"
        aria-haspopup="dialog"
        aria-controls="accessibility-panel"
        aria-expanded={open}
        onClick={() => {
          dialogRef.current?.showModal();
          setOpen(true);
        }}
      >
        <AccessibilityIcon />
        <span className="hidden md:inline">Accessibility</span>
      </button>

      <dialog
        ref={dialogRef}
        id="accessibility-panel"
        className="accessibility-panel"
        aria-labelledby="accessibility-title"
        aria-describedby="accessibility-description"
        onClose={() => {
          setOpen(false);
          launcherRef.current?.focus({ preventScroll: true });
        }}
        onClick={(event) => {
          // Backdrop clicks land on the dialog too; its padding should never dismiss it.
          if (event.target !== event.currentTarget) return;
          const rect = event.currentTarget.getBoundingClientRect();
          if (event.clientX < rect.left || event.clientX > rect.right ||
              event.clientY < rect.top || event.clientY > rect.bottom) {
            event.currentTarget.close();
          }
        }}
        onKeyDown={(event) => {
          // Page-level shortcuts must not submit the onboarding form from this dialog.
          event.stopPropagation();
          if (event.key !== "Tab") return;
          const buttons = event.currentTarget.querySelectorAll<HTMLButtonElement>("button:not([disabled])");
          const first = buttons[0];
          const last = buttons[buttons.length - 1];
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last?.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first?.focus();
          }
        }}
      >
        <div className="sticky top-0 z-10 flex items-start justify-between gap-3 bg-surface pb-2">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex size-11 shrink-0 items-center justify-center rounded-card bg-accent-wash text-accent">
              <AccessibilityIcon />
            </span>
            <p className="font-mono text-micro tracking-widest text-muted uppercase">Your comfort</p>
          </div>
          <button
            type="button"
            autoFocus
            aria-label="Close accessibility settings"
            onClick={() => dialogRef.current?.close()}
            className="flex size-11 shrink-0 items-center justify-center rounded-full border border-line text-title text-muted hover:bg-wash"
          >
            <span aria-hidden="true">×</span>
          </button>
        </div>

        <h2 id="accessibility-title" className="mt-4 text-heading font-semibold tracking-tight text-ink">
          Accessibility
        </h2>
        <p id="accessibility-description" className="mt-2 text-body leading-relaxed text-muted">
          Make Trueplate easier to read and use.
        </p>

        <fieldset className="mt-6 min-w-0">
          <legend className="text-body font-semibold text-ink">Text size</legend>
          <div className="mt-3 grid grid-cols-3 gap-2">
            {TEXT_SIZES.map((size) => (
              <button
                key={size}
                type="button"
                aria-label={`Text size ${size}%`}
                aria-pressed={preferences.textSize === size}
                onClick={() => setPreferences((current) => ({ ...current, textSize: size }))}
                className={`min-h-12 rounded-md border px-2 py-3 font-mono text-body transition-colors ${
                  preferences.textSize === size
                    ? "border-ink bg-ink text-white"
                    : "border-line bg-surface text-ink hover:bg-wash"
                }`}
              >
                {size}%
              </button>
            ))}
          </div>
        </fieldset>

        <div className="mt-5 flex flex-col gap-2">
          <PreferenceToggle
            label="High contrast"
            description="Stronger text and clearer borders."
            checked={preferences.highContrast}
            onToggle={() => setPreferences((current) => ({ ...current, highContrast: !current.highContrast }))}
          />
          <PreferenceToggle
            label="Highlight links"
            description="Underline links so they stand out."
            checked={preferences.highlightLinks}
            onToggle={() => setPreferences((current) => ({ ...current, highlightLinks: !current.highlightLinks }))}
          />
          <PreferenceToggle
            label="Reduce motion"
            description="Limit animations and transitions."
            checked={preferences.reduceMotion}
            onToggle={() => setPreferences((current) => ({ ...current, reduceMotion: !current.reduceMotion }))}
          />
        </div>

        <p className="mt-4 text-caption leading-relaxed text-muted">
          Your device’s reduced-motion setting is always respected.
        </p>
        <div className="mt-5 border-t border-line pt-4">
          <button
            type="button"
            onClick={() => setPreferences({ ...DEFAULT_PREFERENCES })}
            className="min-h-11 w-full rounded-md border border-line px-4 py-2 text-body font-medium text-ink hover:bg-wash"
          >
            Reset preferences
          </button>
          <p role="status" className="mt-3 text-center text-caption leading-relaxed text-muted">
            {canSave
              ? "Changes apply instantly and are saved on this device."
              : "Changes apply for this visit. Your browser has blocked saving preferences."}
          </p>
        </div>
      </dialog>
    </>
  );
}

function PreferenceToggle({ label, description, checked, onToggle }: {
  label: string;
  description: string;
  checked: boolean;
  onToggle: () => void;
}) {
  const descriptionId = useId();
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      aria-describedby={descriptionId}
      onClick={onToggle}
      className={`flex w-full items-center justify-between gap-3 rounded-card border p-4 text-left transition-colors ${
        checked ? "border-accent bg-accent-wash" : "border-line bg-surface hover:bg-wash"
      }`}
    >
      <span className="min-w-0">
        <span className="block text-body font-semibold text-ink">{label}</span>
        <span id={descriptionId} className="mt-1 block text-caption leading-relaxed text-muted">{description}</span>
      </span>
      <span aria-hidden="true" className={`shrink-0 rounded-chip px-2 py-1 font-mono text-micro ${
        checked ? "bg-accent text-white" : "bg-fill text-muted"
      }`}>
        {checked ? "ON" : "OFF"}
      </span>
    </button>
  );
}

function AccessibilityIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <circle cx="12" cy="4" r="2" />
      <path d="m4 8 8 2 8-2M12 10v5m0 0-4 6m4-6 4 6" />
    </svg>
  );
}
