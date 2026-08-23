/**
 * The − / figure / unit / + cluster the wizard uses for age, height, weight and
 * target weight.
 *
 * Only the control is shared, not the label beside it: the two frames arrange
 * that differently — mobile puts the label to the left of the cluster, desktop
 * above it in a three-column grid — so a component that owned the label would
 * need a layout flag and would be doing two jobs.
 *
 * The value arrives as a display string rather than a number so a half-typed
 * "17" on the way to "175" is not clamped up to the minimum mid-keystroke.
 * `onCommit` fires on blur, which is where parsing and clamping happen.
 */
export function NumberStepper({
  value,
  unit,
  label,
  onChange,
  onCommit,
  onStep,
}: {
  value: string;
  unit: string;
  /** Names the input for screen readers; the visible label is a sibling. */
  label: string;
  onChange: (next: string) => void;
  onCommit: () => void;
  onStep: (direction: 1 | -1) => void;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <StepButton onClick={() => onStep(-1)} label={`Decrease ${label}`}>
        −
      </StepButton>
      <div className="flex w-[92px] items-baseline justify-center gap-1.5">
        <input
          inputMode="decimal"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onBlur={onCommit}
          aria-label={label}
          className="tabular w-[52px] border-b border-line-control bg-transparent px-0.5 pb-[3px] text-right font-mono text-input text-ink outline-none focus:border-accent"
        />
        <span className="text-label text-faint">{unit}</span>
      </div>
      <StepButton onClick={() => onStep(1)} label={`Increase ${label}`}>
        +
      </StepButton>
    </div>
  );
}

function StepButton({
  onClick,
  label,
  children,
}: {
  onClick: () => void;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="flex h-10 w-10 flex-none items-center justify-center rounded-full border border-line-control text-[19px] text-ink transition-colors hover:bg-wash"
    >
      {children}
    </button>
  );
}
